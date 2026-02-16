"""Unit tests for RestaurantWineListFinder scoring and URL helpers.

These tests exercise the pure-logic methods that don't need a browser.
"""
import pytest
from unittest.mock import MagicMock

from winerank.crawler.restaurant_finder import (
    RestaurantWineListFinder,
    _SKIP_RE,
    _WINE_PLATFORM_RE,
)


@pytest.fixture
def finder():
    """Create a finder with a mock Playwright Page (no real browser)."""
    mock_page = MagicMock()
    return RestaurantWineListFinder(mock_page)


# ------------------------------------------------------------------
# _normalize_url
# ------------------------------------------------------------------

class TestNormalizeUrl:

    def test_strips_trailing_slash(self):
        assert (RestaurantWineListFinder._normalize_url("https://example.com/path/")
                == "https://example.com/path")

    def test_keeps_root_slash(self):
        assert (RestaurantWineListFinder._normalize_url("https://example.com/")
                == "https://example.com/")

    def test_drops_query_and_fragment(self):
        result = RestaurantWineListFinder._normalize_url(
            "https://example.com/page?q=1#section"
        )
        assert result == "https://example.com/page"


# ------------------------------------------------------------------
# _get_domain
# ------------------------------------------------------------------

class TestGetDomain:

    def test_basic(self):
        assert RestaurantWineListFinder._get_domain("https://www.example.com/path") == "www.example.com"

    def test_lowercase(self):
        assert RestaurantWineListFinder._get_domain("https://WWW.EXAMPLE.COM/") == "www.example.com"


# ------------------------------------------------------------------
# _is_pdf_url
# ------------------------------------------------------------------

class TestIsPdfUrl:

    def test_regular_pdf(self):
        assert RestaurantWineListFinder._is_pdf_url("https://site.com/wine-list.pdf")

    def test_url_encoded_pdf(self):
        assert RestaurantWineListFinder._is_pdf_url("https://site.com/wine-list.pdf%20")

    def test_html_not_pdf(self):
        assert not RestaurantWineListFinder._is_pdf_url("https://site.com/page.html")

    def test_no_extension(self):
        assert not RestaurantWineListFinder._is_pdf_url("https://site.com/page")


# ------------------------------------------------------------------
# _is_wine_platform_url
# ------------------------------------------------------------------

class TestIsWinePlatformUrl:

    def test_binwise_hub(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "https://hub.binwise.com/list/abc"
        )

    def test_bw_winelist_s3(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "http://bw-winelist-website-prod.s3-website-us-west-2.amazonaws.com/xxx"
        )

    def test_starwinelist(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "https://www.starwinelist.com/download/abc"
        )

    def test_regular_url(self):
        assert not RestaurantWineListFinder._is_wine_platform_url(
            "https://www.example.com/wine"
        )


# ------------------------------------------------------------------
# _SKIP_RE – URLs that should be skipped
# ------------------------------------------------------------------

class TestSkipRegex:

    @pytest.mark.parametrize("url", [
        "https://instagram.com/restaurant",
        "https://facebook.com/restaurant",
        "https://www.opentable.com/reservation",
        "mailto:info@restaurant.com",
        "tel:+15551234567",
        "javascript:void(0)",
        "https://restaurant.com/careers",
        "https://restaurant.com/privacy",
        "https://restaurant.com/reservations",
        "https://restaurant.com/gift-cards",
        "https://restaurant.com/private-dining",
    ])
    def test_skips_irrelevant_urls(self, url):
        assert _SKIP_RE.search(url), f"Expected SKIP_RE to match: {url}"

    @pytest.mark.parametrize("url", [
        "https://restaurant.com/wine",
        "https://restaurant.com/menus",
        "https://restaurant.com/beverage-program",
        "https://restaurant.com/about",
    ])
    def test_allows_relevant_urls(self, url):
        assert not _SKIP_RE.search(url), f"Expected SKIP_RE to NOT match: {url}"


# ------------------------------------------------------------------
# _score_link
# ------------------------------------------------------------------

class TestScoreLink:

    def test_exact_wine_keyword_high_score(self, finder):
        score = finder._score_link("wine list", "/wine-list", "")
        assert score > 100

    def test_menu_keyword_lower_than_wine(self, finder):
        wine_score = finder._score_link("wine", "/wine", "")
        menu_score = finder._score_link("menus", "/menus", "")
        assert wine_score > menu_score

    def test_context_boosts_score(self, finder):
        base = finder._score_link("click here", "/link", "")
        boosted = finder._score_link("click here", "/link", "view our wine list here")
        assert boosted > base

    def test_no_match_returns_zero(self, finder):
        score = finder._score_link("about us", "/about", "")
        assert score == 0

    def test_href_slug_match(self, finder):
        score = finder._score_link("selections", "/wine-selections", "")
        assert score > 0

    def test_beverage_program_scores(self, finder):
        score = finder._score_link("beverage program", "/beverage-program", "")
        assert score > 0


# ------------------------------------------------------------------
# _score_wine_keywords_only (stricter — external links)
# ------------------------------------------------------------------

class TestScoreWineKeywordsOnly:

    def test_wine_keyword_scores(self, finder):
        score = finder._score_wine_keywords_only("wine list", "/wine-list")
        assert score > 50

    def test_menu_keyword_does_not_score(self, finder):
        score = finder._score_wine_keywords_only("menus", "/menus")
        assert score == 0

    def test_beverage_keyword_scores(self, finder):
        score = finder._score_wine_keywords_only("beverage menu", "/beverage")
        assert score > 0


# ------------------------------------------------------------------
# Metrics tracking
# ------------------------------------------------------------------

class TestMetrics:

    def test_initial_counters(self, finder):
        assert finder.pages_loaded == 0
        assert finder.tokens_used == 0
        assert len(finder.visited_urls) == 0
