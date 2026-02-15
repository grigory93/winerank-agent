"""Wine list downloader - download PDF/HTML wine lists and compute hashes."""
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from playwright.sync_api import Page

from winerank.config import get_settings


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
    
    async def download_wine_list(
        self,
        url: str,
        restaurant_slug: str,
    ) -> dict:
        """
        Download wine list from URL.
        
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
        
        # Determine file extension and name
        parsed_url = urlparse(url)
        path = parsed_url.path
        
        if path.lower().endswith('.pdf'):
            extension = '.pdf'
            filename = Path(path).name
        elif path.lower().endswith('.html') or path.lower().endswith('.htm'):
            extension = '.html'
            filename = Path(path).name
        else:
            # Default to PDF for wine lists
            extension = '.pdf'
            filename = 'wine_list.pdf'
        
        # Ensure filename is reasonable
        if not filename or filename == extension:
            filename = f"wine_list{extension}"
        
        filename = self._sanitize_filename(filename)
        local_path = restaurant_dir / filename
        
        # Download file
        if extension == '.pdf':
            content = await self._download_file(url)
        else:
            content = await self._download_html(url)
        
        # Save to disk
        if extension == '.pdf':
            local_path.write_bytes(content)
        else:
            local_path.write_text(content, encoding='utf-8')
        
        # Compute hash
        file_hash = self._compute_hash(content if isinstance(content, bytes) else content.encode('utf-8'))
        
        # Get file size
        file_size = local_path.stat().st_size
        
        return {
            "local_file_path": str(local_path),
            "file_hash": file_hash,
            "file_size": file_size,
        }
    
    def download_wine_list_sync(
        self,
        url: str,
        restaurant_slug: str,
    ) -> dict:
        """
        Synchronous version of download_wine_list.
        
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
        
        # Determine file extension and name
        parsed_url = urlparse(url)
        path = parsed_url.path
        
        if path.lower().endswith('.pdf'):
            extension = '.pdf'
            filename = Path(path).name
        elif path.lower().endswith('.html') or path.lower().endswith('.htm'):
            extension = '.html'
            filename = Path(path).name
        else:
            # Default to PDF for wine lists
            extension = '.pdf'
            filename = 'wine_list.pdf'
        
        # Ensure filename is reasonable
        if not filename or filename == extension:
            filename = f"wine_list{extension}"
        
        filename = self._sanitize_filename(filename)
        local_path = restaurant_dir / filename
        
        # Download file synchronously
        if extension == '.pdf':
            content = self._download_file_sync(url)
        else:
            content = self._download_html_sync(url)
        
        # Save to disk
        if extension == '.pdf':
            local_path.write_bytes(content)
        else:
            local_path.write_text(content, encoding='utf-8')
        
        # Compute hash
        file_hash = self._compute_hash(content if isinstance(content, bytes) else content.encode('utf-8'))
        
        # Get file size
        file_size = local_path.stat().st_size
        
        return {
            "local_file_path": str(local_path),
            "file_hash": file_hash,
            "file_size": file_size,
        }
    
    async def _download_file(self, url: str) -> bytes:
        """Download file using httpx (async)."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    
    def _download_file_sync(self, url: str) -> bytes:
        """Download file using httpx (synchronous)."""
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content
    
    async def _download_html(self, url: str) -> str:
        """Download HTML page (async)."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    
    def _download_html_sync(self, url: str) -> str:
        """Download HTML page using Playwright if available, otherwise httpx."""
        if self.page:
            try:
                self.page.goto(url, timeout=self.settings.browser_timeout)
                return self.page.content()
            except Exception:
                # Fall back to httpx
                pass
        
        # Use httpx as fallback
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    
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
