"""Wine list downloader - download PDF/HTML wine lists and compute hashes."""
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from winerank.config import get_settings

logger = logging.getLogger(__name__)

# Patterns that indicate a JS-rendered SPA shell with no real content
_SPA_SHELL_INDICATORS = [
    re.compile(r'<div\s+id=["\']root["\']\s*>\s*</div>', re.IGNORECASE),
    re.compile(r'<div\s+id=["\']app["\']\s*>\s*</div>', re.IGNORECASE),
    re.compile(r'<noscript>.*?enable JavaScript.*?</noscript>', re.IGNORECASE | re.DOTALL),
    re.compile(r'webpackJsonp', re.IGNORECASE),
]


class WineListDownloader:
    """Download wine list files and manage local storage."""
    
    def __init__(self, page: Optional[Page] = None):
        """
        Initialize downloader.
        
        Args:
            page: Optional Playwright page for downloading via browser
        """
        self.page = page
        self.settings = get_settings()
        self.download_dir = self.settings.download_path
    
    def download_wine_list_sync(
        self,
        url: str,
        restaurant_slug: str,
    ) -> dict:
        """
        Synchronous version of download_wine_list.

        Handles URL-encoded paths (e.g. ``wine-list.pdf%20``) and detects
        content type from the HTTP response to avoid saving HTML as PDF.
        For JavaScript-rendered SPA pages (e.g. Binwise), automatically falls
        back to Playwright to render the page and capture real content.

        Args:
            url: URL of wine list (PDF or HTML)
            restaurant_slug: Slug for restaurant (used for directory organization)

        Returns:
            dict with:
                - local_file_path: Path where file was saved
                - file_hash: SHA-256 hash of file
                - file_size: Size in bytes
        """
        # Create restaurant-specific directory
        restaurant_dir = self.download_dir / self._sanitize_filename(restaurant_slug)
        restaurant_dir.mkdir(parents=True, exist_ok=True)

        # Decode URL-encoded path for extension / filename detection
        parsed_url = urlparse(url)
        decoded_path = unquote(parsed_url.path).strip()

        if decoded_path.lower().endswith('.pdf'):
            extension = '.pdf'
            filename = Path(decoded_path).name.strip()
        elif decoded_path.lower().endswith(('.html', '.htm')):
            extension = '.html'
            filename = Path(decoded_path).name.strip()
        else:
            extension = '.pdf'
            filename = 'wine_list.pdf'

        # Ensure filename is reasonable
        if not filename or filename == extension:
            filename = f"wine_list{extension}"

        filename = self._sanitize_filename(filename)

        # Download with content-type detection.
        # First attempt: httpx with browser-like headers.
        # Fallback: Playwright (handles cookies, JS redirects, stricter servers).
        raw_content, content_type = self._download_content(url)

        # Override extension based on actual Content-Type when ambiguous
        if extension == '.pdf' and 'html' in content_type and 'pdf' not in content_type:
            extension = '.html'
            filename = filename.rsplit('.', 1)[0] + '.html' if '.' in filename else 'wine_list.html'
        elif extension == '.html' and 'pdf' in content_type:
            extension = '.pdf'
            filename = filename.rsplit('.', 1)[0] + '.pdf' if '.' in filename else 'wine_list.pdf'

        # For HTML content, check if it's a JS-rendered SPA shell
        if extension == '.html':
            html_text = raw_content.decode('utf-8', errors='replace')
            if self._is_spa_shell(html_text):
                logger.info("Detected SPA shell for %s – rendering with Playwright", url)
                rendered_html = self._render_spa_with_playwright(url)
                if rendered_html:
                    raw_content = rendered_html.encode('utf-8')
                    html_text = rendered_html
                else:
                    logger.warning("Playwright rendering failed for %s", url)

        local_path = restaurant_dir / filename

        # Save to disk
        if extension == '.pdf':
            local_path.write_bytes(raw_content)
        else:
            text = raw_content.decode('utf-8', errors='replace')
            local_path.write_text(text, encoding='utf-8')

        # Compute hash
        file_hash = self._compute_hash(raw_content)

        # Get file size
        file_size = local_path.stat().st_size

        return {
            "local_file_path": str(local_path),
            "file_hash": file_hash,
            "file_size": file_size,
        }

    def _is_spa_shell(self, html_text: str) -> bool:
        """Detect if HTML is a JS-rendered SPA shell with no real content.

        Checks for common SPA indicators: empty root div, webpack bundles,
        noscript tags asking to enable JavaScript, and very little visible
        text content compared to the overall HTML size.
        """
        indicator_hits = sum(
            1 for pattern in _SPA_SHELL_INDICATORS if pattern.search(html_text)
        )
        if indicator_hits >= 2:
            return True

        # Heuristic: extract visible text and check if it's suspiciously short
        soup = BeautifulSoup(html_text, 'html.parser')
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        visible_text = soup.get_text(separator=' ', strip=True)
        if len(html_text) > 500 and len(visible_text) < 100:
            return True

        return False

    # Browser-like headers for httpx requests
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def _download_content(self, url: str) -> tuple[bytes, str]:
        """Download content from *url*, returning ``(raw_bytes, content_type)``.

        Tries httpx first (fast, no browser overhead).  On 401/403 falls
        back to the Playwright page which carries a real browser session
        with cookies, referrer, and a genuine User-Agent.
        """
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=30.0,
                headers=self._BROWSER_HEADERS,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content, response.headers.get("content-type", "").lower()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (401, 403):
                raise
            logger.info(
                "httpx got %s for %s – retrying with Playwright",
                exc.response.status_code, url,
            )

        # Fallback: use Playwright browser (has real cookies / session)
        if not self.page:
            raise httpx.HTTPStatusError(
                "403 Forbidden and no Playwright page available for fallback",
                request=httpx.Request("GET", url),
                response=httpx.Response(403),
            )

        return self._download_via_playwright(url)

    @staticmethod
    def _listing_page_for_download_url(url: str) -> Optional[str]:
        """For URLs like starwinelist.com/.../download/123, return the listing page URL.

        Many sites require you to have visited the listing page first (sets
        cookies / referrer) before the download link works.  Returns None if
        not applicable.
        """
        parsed = urlparse(url)
        path = (parsed.path or "").rstrip("/")
        if "/download/" not in path.lower():
            return None
        # e.g. /wine-place/5182/download/6202 -> /wine-place/5182
        base_path = path.lower().split("/download/")[0]
        if not base_path:
            return None
        new = parsed._replace(path=base_path)
        return urlunparse(new)

    def _download_via_playwright(self, url: str) -> tuple[bytes, str]:
        """Navigate to *url* with Playwright, handling both pages and file downloads.

        Some URLs (e.g. starwinelist.com ``/download/``) only work after visiting
        the listing page first (same site sets cookies).  We do that when
        applicable, then navigate to the download URL.

        Download URLs trigger a browser file-download; we listen for the
        ``download`` event and read the temporary file Playwright produces.

        Uses ``wait_until="load"`` (not ``"networkidle"``) to avoid hanging.
        """
        listing_url = self._listing_page_for_download_url(url)
        if listing_url:
            logger.info("Visiting listing page first: %s", listing_url)
            self.page.goto(
                listing_url,
                timeout=self.settings.browser_timeout,
                wait_until="load",
            )
            self.page.wait_for_timeout(1500)

        download_obj = None

        def _on_download(dl):  # noqa: ANN001
            nonlocal download_obj
            download_obj = dl

        self.page.once("download", _on_download)
        try:
            resp = self.page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="load",
            )
        except Exception:
            # page.goto raises when a download starts instead of a page load
            if download_obj:
                return self._read_playwright_download(download_obj)
            raise

        # Brief wait for a download event that may fire just after load
        self.page.wait_for_timeout(3000)

        if download_obj:
            return self._read_playwright_download(download_obj)

        # Check for HTTP error status
        if resp and resp.status >= 400:
            if resp.status == 403:
                logger.info(
                    "Playwright got 403 for %s – site may block headless browsers; "
                    "try HEADLESS=false to run a visible browser",
                    url,
                )
            raise httpx.HTTPStatusError(
                f"Playwright page got {resp.status}",
                request=httpx.Request("GET", url),
                response=httpx.Response(resp.status),
            )

        # Regular page response
        content_type = (resp.headers.get("content-type", "") if resp else "").lower()
        if "html" in content_type:
            raw_content = self.page.content().encode("utf-8")
        else:
            raw_content = resp.body() if resp else b""
        return raw_content, content_type

    @staticmethod
    def _read_playwright_download(download) -> tuple[bytes, str]:
        """Extract content and infer content-type from a Playwright Download."""
        tmp_path = download.path()
        raw_content = Path(tmp_path).read_bytes() if tmp_path else b""
        suggested = (download.suggested_filename or "").lower()
        if suggested.endswith(".pdf"):
            content_type = "application/pdf"
        elif suggested.endswith((".html", ".htm")):
            content_type = "text/html"
        else:
            content_type = "application/octet-stream"
        return raw_content, content_type

    # Labels for tabs/buttons that expand a wine-list SPA to full content.
    # Checked in order; first visible match is clicked.
    _WINE_LIST_TAB_SELECTORS = [
        'text="Wine List"',
        'text="WINE LIST"',
        'text="Full List"',
        'text="View All"',
        'text="View Full Menu"',
        '.tab-content:has-text("Wine List")',
        '.tab-content:has-text("List")',
    ]

    def _render_spa_with_playwright(self, url: str) -> Optional[str]:
        """Use Playwright to render a JS-heavy SPA and return the DOM HTML.

        Navigates to the URL, waits for the page to finish loading and for
        dynamic content to appear.  For tabbed SPAs (e.g. Binwise digital
        menus), automatically clicks a "Wine List" tab if one exists to
        expand the full content before capturing.
        """
        if not self.page:
            logger.warning("No Playwright page available for SPA rendering")
            return None

        try:
            self.page.goto(url, timeout=self.settings.browser_timeout,
                           wait_until="networkidle")
            # Give JS extra time to finish rendering after network is idle
            self.page.wait_for_timeout(3000)

            # Try to click a "Wine List" tab to expand full content
            self._click_wine_list_tab()

            return self.page.content()
        except Exception as e:
            logger.error("Playwright SPA render failed for %s: %s", url, e)
            return None

    def _click_wine_list_tab(self) -> None:
        """If the page has a 'Wine List' or similar tab, click it.

        Many wine-list platforms (e.g. Binwise) open with a "Table of
        Contents" view that shows only section headings.  Clicking the
        "Wine List" tab switches to a full, scrollable list of all wines.
        """
        for selector in self._WINE_LIST_TAB_SELECTORS:
            try:
                loc = self.page.locator(selector).first
                if loc.is_visible(timeout=2000):
                    logger.info("Clicking SPA tab: %s", selector)
                    loc.click()
                    self.page.wait_for_timeout(5000)
                    return
            except Exception:
                continue
    
    def _compute_hash(self, content: bytes) -> str:
        """
        Compute SHA-256 hash of content.
        
        Args:
            content: File content as bytes
        
        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(content).hexdigest()
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to be filesystem-safe.
        
        Args:
            filename: Original filename
        
        Returns:
            Sanitized filename
        """
        # Remove or replace problematic characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Remove leading/trailing spaces and dots
        filename = filename.strip('. ')
        
        # Limit length
        if len(filename) > 200:
            # Keep extension
            parts = filename.rsplit('.', 1)
            if len(parts) == 2:
                name, ext = parts
                filename = name[:190] + '.' + ext
            else:
                filename = filename[:200]
        
        return filename or 'wine_list'
    
    def file_exists(self, file_hash: str) -> Optional[Path]:
        """
        Check if a file with the given hash already exists.
        
        Args:
            file_hash: SHA-256 hash to search for
        
        Returns:
            Path to existing file, or None if not found
        """
        # Search through all restaurant directories
        for restaurant_dir in self.download_dir.iterdir():
            if not restaurant_dir.is_dir():
                continue
            
            for file_path in restaurant_dir.iterdir():
                if not file_path.is_file():
                    continue
                
                # Compute hash of existing file
                try:
                    if file_path.suffix.lower() == '.pdf':
                        content = file_path.read_bytes()
                    else:
                        content = file_path.read_text(encoding='utf-8').encode('utf-8')
                    
                    existing_hash = self._compute_hash(content)
                    if existing_hash == file_hash:
                        return file_path
                except Exception:
                    continue
        
        return None
