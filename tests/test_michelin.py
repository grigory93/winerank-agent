"""Unit tests for MichelinScraper extraction helpers.

Tests the static/class methods that parse HTML or URLs without needing
a live browser or network access.
"""
import pytest
from bs4 import BeautifulSoup

from winerank.crawler.michelin import MichelinScraper


# ------------------------------------------------------------------
# _extract_distinction
# ------------------------------------------------------------------

class TestExtractDistinction:

    @pytest.mark.parametrize("text, expected", [
        ("Awarded Three Michelin Stars for excellence", "3-stars"),
        ("The restaurant holds 3 Stars in the Guide", "3-stars"),
        ("Exceptional cuisine, worth a special journey – Three Stars", "3-stars"),
        ("Two Michelin Stars for fine dining", "2-stars"),
        ("Holds 2 stars in the 2024 Guide", "2-stars"),
        ("One Michelin Star awarded", "1-star"),
        ("Recently earned 1 Star", "1-star"),
        ("A Bib Gourmand restaurant", "bib-gourmand"),
        ("Just a regular restaurant page", "selected"),
    ])
    def test_distinction_detection(self, text, expected):
        soup = BeautifulSoup(f"<html><body><p>{text}</p></body></html>", "html.parser")
        assert MichelinScraper._extract_distinction(soup) == expected


# ------------------------------------------------------------------
# _extract_location_fallback
# ------------------------------------------------------------------

class TestExtractLocation:

    def test_standard_url(self):
        url = "https://guide.michelin.com/us/en/new-york/new-york/restaurant/per-se"
        city, state = MichelinScraper._extract_location_fallback(url)
        assert city == "New York"
        assert state == "New York"

    def test_california_url(self):
        url = "https://guide.michelin.com/us/en/california/yountville/restaurant/the-french-laundry"
        city, state = MichelinScraper._extract_location_fallback(url)
        assert city == "Yountville"
        assert state == "California"

    def test_dc_url(self):
        url = "https://guide.michelin.com/us/en/district-of-columbia/washington/restaurant/minibar"
        city, state = MichelinScraper._extract_location_fallback(url)
        assert city == "Washington"
        assert state == "DC"

    def test_no_restaurant_in_url(self):
        url = "https://guide.michelin.com/us/en/selection"
        city, state = MichelinScraper._extract_location_fallback(url)
        assert city is None
        assert state is None

    def test_trailing_slash(self):
        url = "https://guide.michelin.com/us/en/illinois/chicago/restaurant/smyth/"
        city, state = MichelinScraper._extract_location_fallback(url)
        assert city == "Chicago"
        assert state == "Illinois"


# ------------------------------------------------------------------
# _extract_price
# ------------------------------------------------------------------

class TestExtractPrice:

    def test_four_dollar_signs(self):
        soup = BeautifulSoup("<html><body><p>Price: $$$$</p></body></html>", "html.parser")
        assert MichelinScraper._extract_price(soup) == "$$$$"

    def test_two_dollar_signs(self):
        soup = BeautifulSoup("<html><body><span>$$</span></body></html>", "html.parser")
        assert MichelinScraper._extract_price(soup) == "$$"

    def test_no_price(self):
        soup = BeautifulSoup("<html><body><p>No price here</p></body></html>", "html.parser")
        assert MichelinScraper._extract_price(soup) is None

    def test_picks_longest(self):
        soup = BeautifulSoup("<html><body><p>$ to $$$$</p></body></html>", "html.parser")
        assert MichelinScraper._extract_price(soup) == "$$$$"


# ------------------------------------------------------------------
# _extract_website_url
# ------------------------------------------------------------------

class TestExtractWebsiteUrl:

    def test_visit_website_link(self):
        html = '<html><body><a href="https://restaurant.com">Visit Website</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        assert MichelinScraper._extract_website_url(soup) == "https://restaurant.com"

    def test_ignores_michelin_links(self):
        html = """<html><body>
        <a href="https://guide.michelin.com/other">Visit Website</a>
        <a href="https://restaurant.com">Visit Website</a>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        result = MichelinScraper._extract_website_url(soup)
        assert result == "https://restaurant.com"

    def test_no_website_link(self):
        html = '<html><body><a href="https://guide.michelin.com/x">More Info</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        assert MichelinScraper._extract_website_url(soup) is None


# ------------------------------------------------------------------
# get_listing_url
# ------------------------------------------------------------------

class TestGetListingUrl:

    @pytest.fixture
    def scraper(self):
        from unittest.mock import MagicMock
        return MichelinScraper(MagicMock(), base_url=MichelinScraper.BASE_URL)

    def test_three_stars(self, scraper):
        url = scraper.get_listing_url("3")
        assert "3-stars-michelin" in url

    def test_gourmand(self, scraper):
        url = scraper.get_listing_url("gourmand")
        assert "bib-gourmand" in url

    def test_pagination(self, scraper):
        url = scraper.get_listing_url("3", page_num=2)
        assert url.endswith("/page/2")

    def test_page_one_no_suffix(self, scraper):
        url = scraper.get_listing_url("3", page_num=1)
        assert "/page/" not in url


# ------------------------------------------------------------------
# scrape_listing_page – error handling and diagnostics
# ------------------------------------------------------------------

class TestScrapeListingPageErrors:

    def test_scrape_listing_page_reraises_with_url_in_message(self):
        """When page.goto fails, scrape_listing_page re-raises with URL in the message."""
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("Page.goto: Page crashed")
        mock_page.is_closed.return_value = True

        scraper = MichelinScraper(
            mock_page, base_url=MichelinScraper.BASE_URL
        )
        url = "https://guide.michelin.com/us/en/selection/united-states/restaurants/1-star-michelin"

        with pytest.raises(Exception) as exc_info:
            scraper.scrape_listing_page(url)

        assert url in str(exc_info.value)
        assert "Error scraping listing page" in str(exc_info.value)

    def test_scrape_listing_page_timeout_reraises_with_url(self):
        """PlaywrightTimeout is re-raised as Exception with URL in message."""
        from unittest.mock import MagicMock
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        mock_page = MagicMock()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout 30000ms exceeded")
        mock_page.is_closed.return_value = False

        scraper = MichelinScraper(
            mock_page, base_url=MichelinScraper.BASE_URL
        )
        url = "https://guide.michelin.com/us/en/selection/restaurants/1-star-michelin"

        with pytest.raises(Exception) as exc_info:
            scraper.scrape_listing_page(url)

        assert url in str(exc_info.value)
        assert "Timeout" in str(exc_info.value)
