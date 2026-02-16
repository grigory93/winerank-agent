"""Unit tests for workflow routing helpers.

Tests the conditional-edge routing functions that decide the next node
in the LangGraph crawler workflow.  No database or browser needed.
"""
import pytest

from winerank.common.models import CrawlStatus
from winerank.crawler.workflow import (
    _route_after_process,
    _route_after_crawl,
    _route_after_save,
)


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

    def test_no_website_goes_to_save(self):
        state = {
            "current_restaurant": {
                "website_url": None,
                "crawl_status": CrawlStatus.NO_WEBSITE,
            },
            "force_recrawl": False,
        }
        assert _route_after_process(state) == "save_result"

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
        assert _route_after_crawl(state) == "save_result"

    def test_no_restaurant(self):
        state = {"current_restaurant": None}
        assert _route_after_crawl(state) == "save_result"


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
