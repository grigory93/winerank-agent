"""Integration tests for WineListDownloader.

These tests hit live websites and require a Playwright browser, so they are
marked ``integration`` and skipped by default in normal ``pytest`` runs.

Run them explicitly:
    uv run pytest tests/integration/test_downloader.py -v -m integration
"""

from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

from winerank.config import get_settings
from winerank.crawler.downloader import WineListDownloader

pytestmark = pytest.mark.integration

# A publicly accessible PDF that httpx can fetch without issues.
PUBLIC_PDF_URL = "https://pdfobject.com/pdf/sample.pdf"

# starwinelist.com blocks both plain HTTP clients and unauthenticated
# browsers with 403 — requires a logged-in session.
STARWINELIST_URL = "https://starwinelist.com/wine-place/5182/download/6202"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser_page():
    """Provide a shared Playwright browser page for the test module."""
    settings = get_settings()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=settings.headless)
        page = browser.new_page()
        yield page
        browser.close()


@pytest.fixture()
def downloader(browser_page):
    """Return a WineListDownloader with a Playwright page."""
    return WineListDownloader(page=browser_page)


@pytest.fixture()
def downloader_no_page():
    """Return a WineListDownloader without a Playwright page."""
    return WineListDownloader()


# ------------------------------------------------------------------
# _download_content – httpx happy path
# ------------------------------------------------------------------

class TestDownloadContentHttpx:
    """Verify that public URLs are fetched directly via httpx."""

    def test_public_pdf_via_httpx(self, downloader):
        raw, content_type = downloader._download_content(PUBLIC_PDF_URL)
        assert len(raw) > 100, "Expected non-empty PDF content"
        assert "pdf" in content_type, f"Expected PDF content-type, got: {content_type}"


# ------------------------------------------------------------------
# _download_content – Playwright fallback
# ------------------------------------------------------------------

class TestDownloadContentFallback:
    """Verify the two-tier download strategy for protected URLs."""

    def test_403_without_page_raises(self, downloader_no_page):
        """Without a Playwright page, a 403 should propagate as an error."""
        with pytest.raises(httpx.HTTPStatusError):
            downloader_no_page._download_content(STARWINELIST_URL)

    def test_starwinelist_requires_auth(self, downloader):
        """starwinelist.com returns 403 even to Playwright (requires login).

        This documents the current behaviour rather than asserting success;
        the fallback mechanism itself is exercised and the error is raised
        cleanly rather than timing out.
        """
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            downloader._download_content(STARWINELIST_URL)
        assert exc_info.value.response.status_code == 403


# ------------------------------------------------------------------
# download_wine_list_sync – end-to-end with file save
# ------------------------------------------------------------------

class TestDownloadWineListSync:
    """End-to-end download that saves to disk."""

    def test_public_pdf_download(self, downloader, tmp_path, monkeypatch):
        """Full download of a public PDF end-to-end."""
        monkeypatch.setattr(downloader, "download_dir", tmp_path)

        result = downloader.download_wine_list_sync(PUBLIC_PDF_URL, "test-restaurant")

        assert "local_file_path" in result
        assert "file_hash" in result
        assert result["file_size"] > 0

        local = Path(result["local_file_path"])
        assert local.exists(), f"Downloaded file not found at {local}"
        assert local.suffix == ".pdf"
        assert local.stat().st_size > 100, "Downloaded file suspiciously small"
