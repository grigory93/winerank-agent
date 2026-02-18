"""Unit tests for workflow routing helpers.

Tests the conditional-edge routing functions that decide the next node
in the LangGraph crawler workflow.  No database or browser needed.
"""
import pytest

from winerank.common.models import CrawlStatus
from winerank.crawler.workflow import (
    _country_to_language_hint,
    _route_after_process,
    _route_after_crawl,
    _route_after_download,
    _route_after_binwise,
    _route_after_save,
)


# ------------------------------------------------------------------
# _country_to_language_hint
# ------------------------------------------------------------------

class TestCountryToLanguageHint:

    def test_france_returns_fr(self):
        assert _country_to_language_hint("France") == "fr"
        assert _country_to_language_hint("france") == "fr"

    def test_spain_and_mexico_return_es(self):
        assert _country_to_language_hint("Spain") == "es"
        assert _country_to_language_hint("Mexico") == "es"
        assert _country_to_language_hint("spain") == "es"
        assert _country_to_language_hint("mexico") == "es"

    def test_usa_and_others_return_en(self):
        assert _country_to_language_hint("USA") == "en"
        assert _country_to_language_hint("Canada") == "en"
        assert _country_to_language_hint("Denmark") == "en"

    def test_none_or_empty_returns_en(self):
        assert _country_to_language_hint(None) == "en"
        assert _country_to_language_hint("") == "en"


# ------------------------------------------------------------------
# _route_after_process
# ------------------------------------------------------------------

class TestRouteAfterProcess:

    def test_no_restaurant_goes_to_save(self):
        state = {"current_restaurant": None}
        assert _route_after_process(state) == "save_result"

    def test_has_website_goes_to_crawl(self):
        state = {
            "current_restaurant": {
                "website_url": "https://example.com",
                "crawl_status": CrawlStatus.HAS_WEBSITE,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "crawl_site"

    def test_no_website_goes_to_search_binwise(self):
        """When no restaurant website found on Michelin page, trigger BinWise search."""
        state = {
            "current_restaurant": {
                "website_url": None,
                "crawl_status": CrawlStatus.NO_WEBSITE,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "search_binwise"

    def test_no_website_empty_string_goes_to_search_binwise(self):
        """Empty string website_url (e.g. from Michelin scrape) also triggers BinWise."""
        state = {
            "current_restaurant": {
                "name": "Some Restaurant",
                "website_url": "",
                "crawl_status": CrawlStatus.NO_WEBSITE,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "search_binwise"

    def test_wine_list_found_skips_crawl(self):
        state = {
            "current_restaurant": {
                "website_url": "https://example.com",
                "crawl_status": CrawlStatus.WINE_LIST_FOUND,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "save_result"

    def test_wine_list_found_with_force_crawls(self):
        state = {
            "current_restaurant": {
                "website_url": "https://example.com",
                "crawl_status": CrawlStatus.WINE_LIST_FOUND,
            },
            "force_recrawl": True,
        }
        assert _route_after_process(state) == "crawl_site"

    def test_download_failed_does_not_skip(self):
        """DOWNLOAD_LIST_FAILED restaurants should be re-crawled."""
        state = {
            "current_restaurant": {
                "website_url": "https://example.com",
                "crawl_status": CrawlStatus.DOWNLOAD_LIST_FAILED,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "crawl_site"

    def test_no_wine_list_does_not_skip(self):
        state = {
            "current_restaurant": {
                "website_url": "https://example.com",
                "crawl_status": CrawlStatus.NO_WINE_LIST,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "crawl_site"


# ------------------------------------------------------------------
# _route_after_crawl
# ------------------------------------------------------------------

class TestRouteAfterCrawl:

    def test_wine_list_url_found(self):
        state = {
            "current_restaurant": {
                "wine_list_url": "https://example.com/wine.pdf",
            },
        }
        assert _route_after_crawl(state) == "download"

    def test_no_wine_list_url(self):
        state = {
            "current_restaurant": {
                "wine_list_url": None,
            },
        }
        assert _route_after_crawl(state) == "search_binwise"

    def test_no_restaurant(self):
        state = {"current_restaurant": None}
        assert _route_after_crawl(state) == "save_result"


# ------------------------------------------------------------------
# _route_after_download
# ------------------------------------------------------------------

class TestRouteAfterDownload:

    def test_success_goes_to_extract_text(self):
        state = {
            "current_restaurant": {
                "local_file_path": "/path/to/file.pdf",
                "download_failed": False,
            },
        }
        assert _route_after_download(state) == "extract_text"

    def test_download_failed_binwise_not_tried_goes_to_search_binwise(self):
        state = {
            "current_restaurant": {
                "wine_list_url": "https://example.com/wine.pdf",
                "local_file_path": None,
                "download_failed": True,
            },
            "binwise_searched": False,
        }
        assert _route_after_download(state) == "search_binwise"

    def test_download_failed_binwise_already_tried_goes_to_save_result(self):
        state = {
            "current_restaurant": {
                "wine_list_url": "https://hub.binwise.com/list/abc",
                "local_file_path": None,
                "download_failed": True,
            },
            "binwise_searched": True,
        }
        assert _route_after_download(state) == "save_result"

    def test_no_restaurant_goes_to_save_result(self):
        state = {"current_restaurant": None}
        assert _route_after_download(state) == "save_result"


# ------------------------------------------------------------------
# _route_after_binwise
# ------------------------------------------------------------------

class TestRouteAfterBinwise:

    def test_url_found_goes_to_download(self):
        state = {
            "current_restaurant": {
                "wine_list_url": "https://hub.binwise.com/list/xyz",
            },
        }
        assert _route_after_binwise(state) == "download"

    def test_no_url_goes_to_save_result(self):
        state = {
            "current_restaurant": {
                "wine_list_url": None,
            },
        }
        assert _route_after_binwise(state) == "save_result"

    def test_no_restaurant_goes_to_save_result(self):
        state = {"current_restaurant": None}
        assert _route_after_binwise(state) == "save_result"


# ------------------------------------------------------------------
# _route_after_save
# ------------------------------------------------------------------

class TestRouteAfterSave:

    def test_more_restaurants_on_page(self):
        state = {
            "current_restaurant_idx": 2,
            "restaurant_urls": ["a", "b", "c", "d"],
            "current_page": 1,
            "total_pages": 1,
        }
        assert _route_after_save(state) == "next_restaurant"

    def test_last_restaurant_single_page_done(self):
        state = {
            "current_restaurant_idx": 3,
            "restaurant_urls": ["a", "b", "c"],
            "current_page": 1,
            "total_pages": 1,
        }
        assert _route_after_save(state) == "done"

    def test_last_restaurant_more_pages(self):
        state = {
            "current_restaurant_idx": 3,
            "restaurant_urls": ["a", "b", "c"],
            "current_page": 1,
            "total_pages": 3,
        }
        assert _route_after_save(state) == "next_page"

    def test_last_restaurant_last_page_done(self):
        state = {
            "current_restaurant_idx": 3,
            "restaurant_urls": ["a", "b", "c"],
            "current_page": 3,
            "total_pages": 3,
        }
        assert _route_after_save(state) == "done"

    def test_circuit_breaker_skip_advances_to_next_page(self):
        """When circuit breaker tripped, current_page already advanced; route to next_page."""
        state = {
            "current_restaurant_idx": 0,
            "restaurant_urls": [],
            "current_page": 2,  # already advanced past failed page 1
            "total_pages": 5,
            "consecutive_fetch_failures": 3,
            "max_consecutive_failures": 3,
        }
        assert _route_after_save(state) == "next_page"

    def test_circuit_breaker_skip_last_page_done(self):
        """When circuit breaker tripped on last page, current_page past total_pages -> done."""
        state = {
            "current_restaurant_idx": 0,
            "restaurant_urls": [],
            "current_page": 6,  # advanced past failed page 5
            "total_pages": 5,
            "consecutive_fetch_failures": 3,
            "max_consecutive_failures": 3,
        }
        assert _route_after_save(state) == "done"

    def test_circuit_breaker_path_not_taken_when_failures_below_threshold(self):
        """When total==0 but failures < max, use normal path (next_page = current_page + 1)."""
        state = {
            "current_restaurant_idx": 1,
            "restaurant_urls": [],
            "current_page": 1,
            "total_pages": 3,
            "consecutive_fetch_failures": 2,
            "max_consecutive_failures": 3,
        }
        assert _route_after_save(state) == "next_page"

    def test_circuit_breaker_zero_total_pages_returns_done(self):
        """When circuit breaker tripped and total_pages is 0, return done."""
        state = {
            "current_restaurant_idx": 0,
            "restaurant_urls": [],
            "current_page": 1,
            "total_pages": 0,
            "consecutive_fetch_failures": 3,
            "max_consecutive_failures": 3,
        }
        assert _route_after_save(state) == "done"

    def test_route_after_save_uses_default_failure_counters(self):
        """Missing consecutive_fetch_failures / max_consecutive_failures default to 0 and 3."""
        state = {
            "current_restaurant_idx": 3,
            "restaurant_urls": ["a", "b", "c"],
            "current_page": 1,
            "total_pages": 2,
        }
        assert _route_after_save(state) == "next_page"
