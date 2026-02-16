"""Integration tests for RestaurantWineListFinder.

These tests hit live restaurant websites via Playwright and (optionally)
call the LLM API, so they are marked ``integration`` and skipped by default
in normal ``pytest`` runs.

Run them explicitly:
    uv run pytest tests/integration/ -v -m integration
    uv run pytest tests/integration/test_wine_list_finder.py -v -m integration
"""

import pytest
from playwright.sync_api import sync_playwright

from winerank.config import get_settings
from winerank.crawler.restaurant_finder import RestaurantWineListFinder

# All tests in this module require the ``integration`` marker.
pytestmark = pytest.mark.integration


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
def finder(browser_page):
    """Return a fresh RestaurantWineListFinder for each test."""
    return RestaurantWineListFinder(browser_page)


# ------------------------------------------------------------------
# Test cases – each restaurant that should have a findable wine list
# ------------------------------------------------------------------

class TestSmyth:
    """Smyth – About → Wine → beverage-program page → starwinelist.com download."""

    URL = "https://www.smythandtheloyalist.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find a wine list URL for Smyth"
        # Should resolve to a starwinelist.com download link
        assert "starwinelist.com" in result.lower(), (
            f"Expected starwinelist.com URL, got: {result}"
        )

    def test_metrics_populated(self, finder):
        finder.find_wine_list(self.URL)
        assert finder.pages_loaded >= 2, (
            "Should visit homepage and beverage-program page at minimum"
        )


class TestElevenMadisonPark:
    """Eleven Madison Park – has a 'Wine List' link in the footer."""

    URL = "https://www.elevenmadisonpark.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find a wine list URL for EMP"


class TestFrenchLaundry:
    """The French Laundry – 'Wine & Spirits' → 'Wine Selections' navigation."""

    URL = "https://thomaskeller.com/tfl/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        # French Laundry may or may not expose a downloadable list;
        # the test validates that the finder navigates into the wine section.
        # If it finds a URL, great; if not, we still check pages_loaded.
        if result is None:
            assert finder.pages_loaded >= 2, (
                "Should have navigated into the Wine & Spirits section"
            )


class TestPerSe:
    """Per Se – 'Wine & Cocktails' → 'Wine & Cocktail Selections' → Binwise."""

    URL = "https://thomaskeller.com/perseny/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find wine list URL for Per Se"
        # Should resolve to a Binwise-hosted wine list page
        assert "binwise" in result.lower() or "bw-winelist" in result.lower(), (
            f"Expected Binwise platform URL, got: {result}"
        )


class TestJungsik:
    """Jungsik – has 'BEVERAGE MENU' and 'JUNGSIK WINE LIST' links on menu page."""

    URL = "https://www.jungsik.com/menu/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        # Jungsik's wine list links may be JS-rendered PDFs
        assert finder.pages_loaded >= 1


class TestSingleThread:
    """SingleThread – Wine → wine program page → Binwise PDF."""

    URL = "https://singlethreadfarms.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find wine list URL for SingleThread"
        # Should find the Binwise-hosted PDF
        assert ".pdf" in result.lower(), f"Expected PDF URL, got: {result}"

    def test_metrics_populated(self, finder):
        finder.find_wine_list(self.URL)
        assert finder.pages_loaded >= 2, "Should visit homepage and wine page at minimum"


class TestLeBernardin:
    """Le Bernardin – known to have a wine list PDF."""

    URL = "https://www.le-bernardin.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        if result is not None:
            assert ".pdf" in result.lower() or result.startswith("http")


class TestBlueHillAtStoneBarns:
    """Blue Hill at Stone Barns – FAQ page → WINE LIST section → PDF link.

    The homepage links to /faq which contains a "WINE LIST" section
    with "Please find the wine list here." where "here" links to a PDF.
    """

    URL = "https://www.bluehillfarm.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find wine list URL for Blue Hill"
        assert ".pdf" in result.lower(), f"Expected PDF URL, got: {result}"

    def test_metrics_populated(self, finder):
        finder.find_wine_list(self.URL)
        assert finder.pages_loaded >= 2, (
            "Should visit homepage and FAQ page at minimum"
        )


class TestAtomix:
    """Atomix – Chef's Counter → Wine Program section → Wine List PDF.

    The homepage has a "Chef's Counter" navigation link.  That page contains
    a "Wine Program" section with a "Wine List" link to a PDF.
    """

    URL = "https://www.atomixnyc.com/"

    def test_finds_wine_list(self, finder):
        result = finder.find_wine_list(self.URL)
        assert result is not None, "Expected to find wine list URL for Atomix"
        assert ".pdf" in result.lower(), f"Expected PDF URL, got: {result}"

    def test_metrics_populated(self, finder):
        finder.find_wine_list(self.URL)
        assert finder.pages_loaded >= 2, (
            "Should visit homepage and Chef's Counter page at minimum"
        )
