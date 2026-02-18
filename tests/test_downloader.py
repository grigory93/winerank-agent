"""Unit tests for WineListDownloader."""
import pytest

from winerank.crawler.downloader import WineListDownloader


@pytest.fixture
def downloader():
    """Create a WineListDownloader without a Playwright page."""
    return WineListDownloader()


# ------------------------------------------------------------------
# _sanitize_filename
# ------------------------------------------------------------------

class TestSanitizeFilename:

    def test_normal_filename(self, downloader):
        assert downloader._sanitize_filename("wine_list.pdf") == "wine_list.pdf"

    def test_removes_invalid_chars(self, downloader):
        assert downloader._sanitize_filename('wine<list>.pdf') == "wine_list_.pdf"

    def test_strips_dots_and_spaces(self, downloader):
        assert downloader._sanitize_filename("  .wine_list.pdf  ") == "wine_list.pdf"

    def test_truncates_long_filename(self, downloader):
        long_name = "a" * 250 + ".pdf"
        result = downloader._sanitize_filename(long_name)
        assert len(result) <= 200
        assert result.endswith(".pdf")

    def test_empty_returns_default(self, downloader):
        assert downloader._sanitize_filename("") == "wine_list"

    def test_only_dots_returns_default(self, downloader):
        assert downloader._sanitize_filename("...") == "wine_list"


# ------------------------------------------------------------------
# _compute_hash
# ------------------------------------------------------------------

class TestComputeHash:

    def test_deterministic(self, downloader):
        content = b"hello world"
        h1 = downloader._compute_hash(content)
        h2 = downloader._compute_hash(content)
        assert h1 == h2

    def test_different_content_different_hash(self, downloader):
        h1 = downloader._compute_hash(b"content a")
        h2 = downloader._compute_hash(b"content b")
        assert h1 != h2

    def test_returns_hex_string(self, downloader):
        h = downloader._compute_hash(b"test")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex = 64 chars


# ------------------------------------------------------------------
# _is_spa_shell  (complements test_spa_shell_detection in test_text_extractor)
# ------------------------------------------------------------------

class TestIsSpaShell:

    def test_minimal_react_shell(self, downloader):
        # Needs 2+ indicators or the length heuristic (>500 chars, <100 visible)
        html = ('<html><head><title>App</title></head><body>'
                '<noscript>You need to enable JavaScript to run this app.</noscript>'
                '<div id="root"></div>'
                '<script src="main.js"></script>'
                '</body></html>')
        assert downloader._is_spa_shell(html) is True

    def test_content_rich_page(self, downloader):
        html = ("<html><body><h1>Wine List</h1>" +
                "<p>Chateau Margaux 2015</p>" * 20 +
                "</body></html>")
        assert downloader._is_spa_shell(html) is False

    def test_noscript_with_enable_js(self, downloader):
        html = ('<html><body>'
                '<noscript>You need to enable JavaScript to run this app.</noscript>'
                '<div id="app"></div>'
                '</body></html>')
        assert downloader._is_spa_shell(html) is True

    def test_short_html_not_spa(self, downloader):
        html = "<html><body><p>Hello</p></body></html>"
        assert downloader._is_spa_shell(html) is False


# ------------------------------------------------------------------
# _WINE_LIST_TAB_SELECTORS – include French and Spanish labels
# ------------------------------------------------------------------

class TestWineListTabSelectors:

    def test_english_selectors_present(self, downloader):
        selectors = downloader._WINE_LIST_TAB_SELECTORS
        assert 'text="Wine List"' in selectors
        assert 'text="WINE LIST"' in selectors

    def test_french_selectors_present(self, downloader):
        selectors = downloader._WINE_LIST_TAB_SELECTORS
        assert 'text="Carte des vins"' in selectors
        assert 'text="Vins"' in selectors

    def test_spanish_selectors_present(self, downloader):
        selectors = downloader._WINE_LIST_TAB_SELECTORS
        assert 'text="Carta de vinos"' in selectors
        assert 'text="Vinos"' in selectors
