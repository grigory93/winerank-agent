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
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session"):
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
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 2,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session"),
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
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
            "michelin_level": "1-star",
            "current_page": 2,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 3,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session"):
            result = fetch_listing_page_node(cast(CrawlerState, state))

        assert result["consecutive_fetch_failures"] == 1
        assert "Page 2 attempt 1" in result["errors"][0]

    def test_page_crashed_calls_recover_browser(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Page.goto: Page crashed")

        state = {
            "job_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session"),
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
            fetch_listing_page_node(cast(CrawlerState, state))

        mock_recover.assert_called_once()

    def test_page_closed_calls_recover_browser(self, mock_get_page_and_scraper):
        _, mock_scraper = mock_get_page_and_scraper
        mock_scraper.get_listing_url.return_value = "https://guide.michelin.com/..."
        mock_scraper.scrape_listing_page.side_effect = Exception("Page closed")

        state = {
            "job_id": 1,
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with (
            patch("winerank.crawler.workflow.get_session"),
            patch("winerank.crawler.workflow._recover_browser") as mock_recover,
        ):
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
            "michelin_level": "1-star",
            "current_page": 1,
            "restaurants_found": 0,
            "consecutive_fetch_failures": 2,
            "max_consecutive_failures": 3,
            "errors": [],
        }

        with patch("winerank.crawler.workflow.get_session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
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
