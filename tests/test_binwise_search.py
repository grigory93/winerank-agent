"""Unit tests for BinWise fallback search and result validation."""
import pytest
from unittest.mock import patch, MagicMock

from winerank.crawler.binwise_search import (
    search_binwise,
    _validate_binwise_result,
)


# ------------------------------------------------------------------
# _validate_binwise_result
# ------------------------------------------------------------------

class TestValidateBinwiseResult:

    def test_empty_url_returns_false(self):
        assert _validate_binwise_result("", "Quince") is False
        assert _validate_binwise_result("https://other.com", "Quince") is False

    def test_page_title_contains_restaurant_name(self):
        html = "<html><head><title>Quince - Wine List</title></head><body></body></html>"
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.text = html
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/quince", "Quince"
            ) is True

    def test_page_title_contains_different_restaurant_returns_false(self):
        html = "<html><head><title>Other Restaurant - Wine List</title></head><body></body></html>"
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.text = html
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/other", "Quince"
            ) is False

    def test_restaurant_name_in_h1_returns_true(self):
        html = (
            "<html><head><title>Binwise Menu</title></head>"
            "<body><h1>Quince Wine List</h1></body></html>"
        )
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.text = html
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/quince", "Quince"
            ) is True

    def test_short_name_exact_match_per_se(self):
        html = "<html><head><title>Per Se - Wine &amp; Beverage</title></head><body></body></html>"
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.text = html
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/perse", "Per Se"
            ) is True

    def test_short_name_per_alone_does_not_match_per_se(self):
        html = "<html><head><title>Per - Something</title></head><body></body></html>"
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.text = html
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/per", "Per Se"
            ) is False

    def test_network_error_returns_false(self):
        with patch("winerank.crawler.binwise_search.httpx") as mock_httpx:
            mock_httpx.Client.return_value.__enter__.return_value.get.side_effect = Exception(
                "Connection error"
            )
            assert _validate_binwise_result(
                "https://hub.binwise.com/list/xyz", "Quince"
            ) is False


# ------------------------------------------------------------------
# search_binwise (two-pass and validation)
# ------------------------------------------------------------------

class TestSearchBinwise:

    def test_empty_restaurant_name_returns_none(self):
        assert search_binwise("") is None
        assert search_binwise("   ") is None

    def test_pass1_pdf_returns_validated_result(self):
        with patch("winerank.crawler.binwise_search._run_one_pass") as mock_run:
            mock_run.return_value = "https://hub.binwise.com/list/quince"
            result = search_binwise("Quince")
            assert result == "https://hub.binwise.com/list/quince"
            assert mock_run.call_count == 1
            call_args = mock_run.call_args
            assert "pdf" in call_args[0][1]

    def test_pass1_no_results_pass2_returns_validated_result(self):
        with patch("winerank.crawler.binwise_search._run_one_pass") as mock_run:
            mock_run.side_effect = [None, "https://hub.binwise.com/list/quince-html"]
            result = search_binwise("Quince")
            assert result == "https://hub.binwise.com/list/quince-html"
            assert mock_run.call_count == 2
            assert "pdf" in mock_run.call_args_list[0][0][1]
            assert "pdf" not in mock_run.call_args_list[1][0][1]

    def test_both_passes_return_none(self):
        with patch("winerank.crawler.binwise_search._run_one_pass") as mock_run:
            mock_run.return_value = None
            result = search_binwise("Quince")
            assert result is None
            assert mock_run.call_count == 2

    def test_google_search_raises_returns_none_gracefully(self):
        with patch("winerank.crawler.binwise_search._run_one_pass") as mock_run:
            mock_run.side_effect = Exception("Network error")
            result = search_binwise("Quince")
            assert result is None
