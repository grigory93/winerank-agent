"""Restaurant website wine list finder - navigate restaurant sites to find wine lists."""
import logging
from typing import Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from winerank.config import get_settings

logger = logging.getLogger(__name__)


class RestaurantWineListFinder:
    """Find wine lists on restaurant websites using tiered search strategies."""

    # Keywords for wine list links (ordered by specificity – highest first)
    WINE_KEYWORDS = [
        "wine list",
        "wine program",
        "wine menu",
        "wine",
        "cellar",
        "sommelier",
        "by the glass",
        "beverage",
        "drink",
    ]

    # Fallback: look for generic menu pages that *might* host the wine list
    MENU_KEYWORDS = [
        "menu",
        "dine",
        "dining",
        "food & drink",
        "food and drink",
    ]

    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()
        self.visited_urls: Set[str] = set()
        self.pages_loaded = 0

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def find_wine_list(
        self,
        restaurant_url: str,
        cached_wine_list_url: Optional[str] = None,
    ) -> Optional[str]:
        """Find a wine list URL on a restaurant website (tiered approach)."""
        self.visited_urls.clear()
        self.pages_loaded = 0

        # Tier 1 – try the previously-known URL
        if cached_wine_list_url:
            logger.debug("  Tier 1: trying cached URL %s", cached_wine_list_url)
            if self._verify_url(cached_wine_list_url):
                return cached_wine_list_url

        # Tier 2 – keyword-based link search (wine-specific terms)
        logger.debug("  Tier 2: keyword search (wine)")
        url = self._search_by_keywords(
            restaurant_url,
            self.WINE_KEYWORDS,
            max_depth=self.settings.restaurant_website_depth,
        )
        if url:
            return url

        # Tier 3 – broader search via menu pages
        logger.debug("  Tier 3: keyword search (menu)")
        url = self._search_by_keywords(
            restaurant_url,
            self.MENU_KEYWORDS,
            max_depth=2,
        )
        if url:
            return url

        return None

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _verify_url(self, url: str) -> bool:
        """Quick HEAD-style check that a URL is reachable."""
        try:
            resp = self.page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            return bool(resp and resp.ok)
        except Exception:
            return False

    def _search_by_keywords(
        self,
        start_url: str,
        keywords: list[str],
        max_depth: int,
        current_depth: int = 0,
    ) -> Optional[str]:
        if current_depth >= max_depth:
            return None
        if self.pages_loaded >= self.settings.max_restaurant_pages:
            return None

        start_url = self._normalize_url(start_url)
        if start_url in self.visited_urls:
            return None
        self.visited_urls.add(start_url)

        try:
            self.page.goto(
                start_url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            self.pages_loaded += 1

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")
            base_domain = self._get_domain(start_url)

            # Pass 1 – look for direct PDF links on this page
            pdf_url = self._find_pdf_link(soup, start_url, base_domain)
            if pdf_url:
                return pdf_url

            # Pass 2 – score all internal links and follow the best ones
            scored_links = self._score_page_links(
                soup, start_url, base_domain, keywords,
            )
            scored_links.sort(reverse=True, key=lambda x: x[0])

            for _score, link_url, _text in scored_links:
                result = self._search_by_keywords(
                    link_url, keywords, max_depth, current_depth + 1,
                )
                if result:
                    return result

            return None

        except PlaywrightTimeout:
            logger.debug("  Timeout loading %s", start_url)
            return None
        except Exception as exc:
            logger.debug("  Error loading %s: %s", start_url, exc)
            return None

    # -----------------------------------------------------------------
    # PDF detection
    # -----------------------------------------------------------------

    def _find_pdf_link(
        self, soup: BeautifulSoup, page_url: str, base_domain: str,
    ) -> Optional[str]:
        """Return the first PDF link on the page that looks like a wine list."""
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)
            if not self._is_pdf_url(abs_url):
                continue
            # Accept any PDF that we reached via wine/menu navigation.
            # Additionally boost if text or URL contain wine hints.
            return abs_url
        return None

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Check whether a URL points to a PDF."""
        path = urlparse(url).path.lower()
        return path.endswith(".pdf")

    # -----------------------------------------------------------------
    # Link scoring
    # -----------------------------------------------------------------

    def _score_page_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
        keywords: list[str],
    ) -> list[tuple[int, str, str]]:
        """Score and return internal links matching the keyword list."""
        results: list[tuple[int, str, str]] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)

            # Skip external, visited, and anchor-only links
            if self._get_domain(abs_url) != base_domain:
                continue
            norm = self._normalize_url(abs_url)
            if norm in self.visited_urls:
                continue

            text = a.get_text(strip=True).lower()
            score = self._score_link(text, href, keywords)
            if score > 0:
                results.append((score, abs_url, text))

        return results

    @staticmethod
    def _score_link(text: str, href: str, keywords: list[str]) -> int:
        score = 0
        href_lower = href.lower()

        for rank, kw in enumerate(keywords):
            weight = len(keywords) - rank          # higher weight for earlier kw

            if kw == text:                         # exact match on link text
                score += weight * 10
            elif kw in text:                       # partial match on link text
                score += weight * 5
            # Match in the URL path
            slug = kw.replace(" ", "-")
            if slug in href_lower:
                score += weight * 3

        return score

    # -----------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------

    @staticmethod
    def _normalize_url(url: str) -> str:
        parsed = urlparse(url)
        out = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if out.endswith("/") and len(parsed.path) > 1:
            out = out[:-1]
        return out

    @staticmethod
    def _get_domain(url: str) -> str:
        return urlparse(url).netloc.lower()
