"""Unit tests for workflow circuit breaker and browser recovery.

Tests fetch_listing_page_node error handling and _recover_browser without
a real browser or database.
"""
from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from winerank.crawler.workflow import (
    CrawlerState,
    fetch_listing_page_node,
    _recover_browser,
)


def _mock_site(mock_get_session):
    """Configure get_session mock so SiteOfRecord lookup returns a site with site_url."""
    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    mock_site = MagicMock()
    mock_site.site_url = "https://guide.michelin.com/us/en/selection/united-states/restaurants"
    q = mock_session.query.return_value.filter_by.return_value
    q.first.return_value = mock_site
    return mock_session


# ------------------------------------------------------------------
# fetch_listing_page_node – circuit breaker and error paths
# ------------------------------------------------------------------

class TestFetchListingPageNodeCircuitBreaker:

    @pytest.fixture(autouse=True)
    def mock_get_page_and_scraper(self):
        """Provide a mock page and scraper that raises on scrape_listing_page."""
        mock_page = MagicMock()
        with (
            patch("winerank.crawler.workflow._get_page", return_value=mock_page),
            patch("winerank.crawler.workflow.MichelinScraper") as mock_scraper_cls,
        ):
            mock_scraper = mock_scraper_cls.return_value
            yield mock_page, mock_scraper

    def test_first_failure_increments_counter_and_does_not_advance_page(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Network error")

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session") as mock_get_session:
            _mock_site(mock_get_session)
            result = fetch_listing_page_node(cast(CrawlerState, state))

        assert result["consecutive_fetch_failures"] == 1
        assert len(result["errors"]) == 1
        assert "Page 1 attempt 1" in result["errors"][0]
        assert "current_page" not in result or result.get("current_page") == 1

    def test_third_failure_trips_circuit_breaker_and_advances_page(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Page crashed")

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 2,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session") as mock_get_session,
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
            _mock_site(mock_get_session)
            result = fetch_listing_page_node(cast(CrawlerState, state))

        assert result["consecutive_fetch_failures"] == 3
        assert result["restaurant_urls"] == []
        assert result["current_restaurant_idx"] == 0
        assert result["current_page"] == 2
        assert len(result["errors"]) == 1
        mock_recover.assert_called_once()

    def test_after_breaker_new_page_failure_count_starts_at_one(self, mock_get_page_and_scraper):
        """When base >= max_failures (e.g. after a skip), next failure is counted as 1."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Timeout")

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 2,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 3,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session") as mock_get_session:
            _mock_site(mock_get_session)
            result = fetch_listing_page_node(cast(CrawlerState, state))

        assert result["consecutive_fetch_failures"] == 1
        assert "Page 2 attempt 1" in result["errors"][0]

    def test_page_crashed_calls_recover_browser(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Page.goto: Page crashed")

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session") as mock_get_session,
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
            _mock_site(mock_get_session)
            fetch_listing_page_node(cast(CrawlerState, state))

        mock_recover.assert_called_once()

    def test_page_closed_calls_recover_browser(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Page closed")

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session") as mock_get_session,
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
            _mock_site(mock_get_session)
            fetch_listing_page_node(cast(CrawlerState, state))

        mock_recover.assert_called_once()

    def test_success_resets_consecutive_fetch_failures(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["https://guide.michelin.com/us/en/ny/restaurant/one"],
            "total_restaurants": 1,
            "total_pages": 1,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 2,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session") as mock_get_session:
            mock_session = _mock_site(mock_get_session)
            mock_job = MagicMock()
            mock_session.query.return_value.filter_by.return_value.first.side_effect = [
                mock_session.query.return_value.filter_by.return_value.first.return_value,  # site
                mock_job,  # job for progress persist
            ]
            result = fetch_listing_page_node(cast(CrawlerState, state))

        assert result["consecutive_fetch_failures"] == 0
        assert len(result["restaurant_urls"]) == 1


# ------------------------------------------------------------------
# _recover_browser
# ------------------------------------------------------------------

class TestRecoverBrowser:

    def test_no_playwright_instance_returns_without_raising(self):
        """When _playwright_instance is None, _recover_browser logs and returns."""
        with patch("winerank.crawler.workflow._playwright_instance", None):
            _recover_browser()
        # No exception; may log error


# ------------------------------------------------------------------
# fetch_listing_page_node – paging advancement
# ------------------------------------------------------------------

class TestFetchListingPagePagingAdvancement:
    """Tests that fetch_listing_page_node correctly advances current_page
    when called after finishing all restaurants on a page."""

    @pytest.fixture(autouse=True)
    def mock_get_page_and_scraper(self):
        """Provide a mock page and scraper that returns success."""
        mock_page = MagicMock()
        with (
            patch("winerank.crawler.workflow._get_page", return_value=mock_page),
            patch("winerank.crawler.workflow.MichelinScraper") as mock_scraper_cls,
            patch("winerank.crawler.workflow.get_session") as mock_get_session,
        ):
            mock_scraper = mock_scraper_cls.return_value
            mock_session = MagicMock()
            mock_get_session.return_value.__enter__.return_value = mock_session
            mock_site = MagicMock()
            mock_site.site_url = "https://guide.michelin.com/us/en/selection/united-states/restaurants"
            mock_session.query.return_value.filter_by.return_value.first.side_effect = [
                mock_site,  # SiteOfRecord lookup
                None,      # Job lookup for progress
            ]
            yield mock_page, mock_scraper

    def test_first_page_fetch_does_not_advance_page(self, mock_get_page_and_scraper):
        """Initial fetch (empty urls_so_far) should use current_page as-is."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/.../page/1"
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["url1", "url2", "url3"],
            "total_restaurants": 100,
            "total_pages": 3,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "3",
            "current_page": 1,
            "restaurant_urls": [],  # Empty - first fetch
            "current_restaurant_idx": 0,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "errors": [],
        }

        result = fetch_listing_page_node(cast(CrawlerState, state))

        # Should fetch page 1 and return current_page: 1
        mock_scraper.get_listing_url.assert_called_once_with("3", 1)
        assert result["current_page"] == 1
        assert result["restaurant_urls"] == ["url1", "url2", "url3"]
        assert result["total_pages"] == 3

    def test_after_finishing_page_advances_to_next_page(self, mock_get_page_and_scraper):
        """After processing all restaurants on page 1, should fetch page 2."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/.../page/2"
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["url4", "url5", "url6"],
            "total_restaurants": 100,
            "total_pages": 3,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "3",
            "current_page": 1,
            "restaurant_urls": ["url1", "url2", "url3"],  # Previous page's URLs
            "current_restaurant_idx": 3,  # Finished all (idx >= len)
            "restaurants_found": 3,
            "consecutive_fetch_failures": 0,
            "errors": [],
        }

        result = fetch_listing_page_node(cast(CrawlerState, state))

        # Should detect we finished page 1 and fetch page 2
        mock_scraper.get_listing_url.assert_called_once_with("3", 2)
        assert result["current_page"] == 2
        assert result["restaurant_urls"] == ["url4", "url5", "url6"]
        assert result["current_restaurant_idx"] == 0  # Reset for new page

    def test_middle_of_page_does_not_advance(self, mock_get_page_and_scraper):
        """In the middle of processing a page, should not advance (shouldn't be called)."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/.../page/1"
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["url1", "url2", "url3"],
            "total_restaurants": 100,
            "total_pages": 3,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "3",
            "current_page": 1,
            "restaurant_urls": ["url1", "url2", "url3"],
            "current_restaurant_idx": 1,  # In the middle (idx < len)
            "restaurants_found": 3,
            "consecutive_fetch_failures": 0,
            "errors": [],
        }

        result = fetch_listing_page_node(cast(CrawlerState, state))

        # Should still use current_page (though normally we wouldn't call fetch_listing_page mid-page)
        mock_scraper.get_listing_url.assert_called_once_with("3", 1)
        assert result["current_page"] == 1

    def test_advances_through_multiple_pages(self, mock_get_page_and_scraper):
        """Verify page 2 -> page 3 advancement works too."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/.../page/3"
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["url7", "url8"],
            "total_restaurants": 100,
            "total_pages": 3,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "2",
            "current_page": 2,
            "restaurant_urls": ["url4", "url5", "url6"],  # Page 2's URLs
            "current_restaurant_idx": 3,  # Finished page 2
            "restaurants_found": 6,
            "consecutive_fetch_failures": 0,
            "errors": [],
        }

        result = fetch_listing_page_node(cast(CrawlerState, state))

        # Should advance from page 2 to page 3
        mock_scraper.get_listing_url.assert_called_once_with("2", 3)
        assert result["current_page"] == 3
        assert result["restaurant_urls"] == ["url7", "url8"]

    def test_circuit_breaker_already_advanced_does_not_double_advance(self, mock_get_page_and_scraper):
        """When circuit breaker already advanced current_page, don't advance again."""
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/.../page/2"
        mock_scraper.scrape_listing_page.return_value = {
            "restaurant_urls": ["url4", "url5"],
            "total_restaurants": 100,
            "total_pages": 3,
        }

        state = {
            "job_id": 1,
            "site_of_record_id": 1,
            "michelin_level": "3",
            "current_page": 2,  # Circuit breaker already advanced this
            "restaurant_urls": [],  # Empty from circuit breaker
            "current_restaurant_idx": 0,
            "restaurants_found": 3,
            "consecutive_fetch_failures": 0,
            "errors": [],
        }

        result = fetch_listing_page_node(cast(CrawlerState, state))

        # Should use page 2 as-is (not advance to 3)
        # because urls_so_far is empty, condition fails
        mock_scraper.get_listing_url.assert_called_once_with("3", 2)
        assert result["current_page"] == 2
