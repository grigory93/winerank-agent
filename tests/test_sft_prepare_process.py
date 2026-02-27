"""Tests for prepare/process functions across all three pipeline phases."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.executor.types import LLMRequest, LLMResponse
from winerank.sft.schemas import (
    ManifestEntry,
    SampleManifestEntry,
    TaxonomyNode,
    TaxonomyResult,
    PageParseResult,
    WineEntry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(data_dir=str(tmp_path / "sft"), training_data_mode="text")


@pytest.fixture
def progress(sft_settings):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(sft_settings.progress_file)


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a tiny placeholder file (content doesn't matter for mocked tests)."""
    p = tmp_path / "test.pdf"
    p.write_bytes(b"%PDF-1.4 placeholder")
    return p


# ---------------------------------------------------------------------------
# Taxonomy prepare
# ---------------------------------------------------------------------------

class TestPrepareTaxonomyRequests:
    def test_returns_request_per_valid_entry(self, tmp_path, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import prepare_taxonomy_requests

        f = tmp_path / "list.pdf"
        f.write_bytes(b"%PDF")
        entry = ManifestEntry(
            list_id="list1", restaurant_name="R1",
            file_path=str(f), file_type="pdf",
        )
        with patch("winerank.sft.taxonomy_extractor.extract_fulltext", return_value="wine list text"):
            reqs = prepare_taxonomy_requests([entry], sft_settings, progress)

        assert len(reqs) == 1
        assert reqs[0].custom_id == "taxonomy__list1"
        assert reqs[0].model == sft_settings.taxonomy_model
        assert reqs[0].response_format == {"type": "json_object"}

    def test_skips_already_completed_entries(self, tmp_path, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import prepare_taxonomy_requests

        f = tmp_path / "list.pdf"
        f.write_bytes(b"%PDF")
        entry = ManifestEntry(
            list_id="done_list", restaurant_name="R1",
            file_path=str(f), file_type="pdf",
        )
        progress.mark_taxonomy_done("done_list", "OK")

        with patch("winerank.sft.taxonomy_extractor.extract_fulltext", return_value="text"):
            reqs = prepare_taxonomy_requests([entry], sft_settings, progress)

        assert reqs == []

    def test_force_reruns_completed_entries(self, tmp_path, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import prepare_taxonomy_requests

        f = tmp_path / "list.pdf"
        f.write_bytes(b"%PDF")
        entry = ManifestEntry(
            list_id="done_list", restaurant_name="R1",
            file_path=str(f), file_type="pdf",
        )
        progress.mark_taxonomy_done("done_list", "OK")

        with patch("winerank.sft.taxonomy_extractor.extract_fulltext", return_value="text"):
            reqs = prepare_taxonomy_requests([entry], sft_settings, progress, force=True)

        assert len(reqs) == 1

    def test_skips_missing_files(self, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import prepare_taxonomy_requests

        entry = ManifestEntry(
            list_id="missing", restaurant_name="R1",
            file_path="/nonexistent/file.pdf", file_type="pdf",
        )
        reqs = prepare_taxonomy_requests([entry], sft_settings, progress)
        assert reqs == []
        # Should mark it as error
        assert progress.get_taxonomy_status("missing") == "ERROR"

    def test_full_text_included_in_prompt(self, tmp_path, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import prepare_taxonomy_requests

        f = tmp_path / "list.pdf"
        f.write_bytes(b"%PDF")
        entry = ManifestEntry(
            list_id="l1", restaurant_name="R",
            file_path=str(f), file_type="pdf",
        )
        full_text = "Champagne\nBurgundy\nBordeaux"

        with patch("winerank.sft.taxonomy_extractor.extract_fulltext", return_value=full_text):
            reqs = prepare_taxonomy_requests([entry], sft_settings, progress)

        # The full text should appear in the user message
        user_content = reqs[0].messages[1]["content"]
        assert full_text in user_content


class TestProcessTaxonomyResponses:
    def test_processes_ok_response(self, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import process_taxonomy_responses

        response = LLMResponse(
            custom_id="taxonomy__list1",
            content=json.dumps({
                "status": "OK",
                "restaurant_name": "Test Restaurant",
                "categories": [{"name": "Champagne", "subcategories": []}],
            }),
            tokens={"input": 100, "output": 50, "cached": 0},
        )
        results = process_taxonomy_responses([response], sft_settings, progress)

        assert "list1" in results
        assert results["list1"].status == "OK"
        assert results["list1"].restaurant_name == "Test Restaurant"
        assert len(results["list1"].categories) == 1

    def test_processes_not_a_list_response(self, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import process_taxonomy_responses

        response = LLMResponse(
            custom_id="taxonomy__list2",
            content=json.dumps({"status": "NOT_A_LIST"}),
            tokens={"input": 50, "output": 10, "cached": 0},
        )
        results = process_taxonomy_responses([response], sft_settings, progress)
        assert "list2" in results
        assert results["list2"].status == "NOT_A_LIST"

    def test_handles_error_response(self, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import process_taxonomy_responses

        response = LLMResponse(
            custom_id="taxonomy__list3",
            content="",
            tokens={"input": 0, "output": 0, "cached": 0},
            error="Connection failed",
        )
        results = process_taxonomy_responses([response], sft_settings, progress)
        assert "list3" not in results

    def test_saves_taxonomy_to_disk(self, sft_settings, progress):
        from winerank.sft.taxonomy_extractor import load_taxonomy, process_taxonomy_responses

        sft_settings.taxonomy_dir.mkdir(parents=True, exist_ok=True)
        response = LLMResponse(
            custom_id="taxonomy__list4",
            content=json.dumps({
                "status": "OK",
                "categories": [{"name": "Red", "subcategories": []}],
            }),
            tokens={"input": 100, "output": 50, "cached": 0},
        )
        process_taxonomy_responses([response], sft_settings, progress)

        loaded = load_taxonomy(sft_settings.taxonomy_dir, "list4")
        assert loaded is not None
        assert loaded.status == "OK"


# ---------------------------------------------------------------------------
# Wine Parsing prepare
# ---------------------------------------------------------------------------

class TestPreparseParseRequests:
    def _make_sample(self, source_file, list_id="list1", seg_idx=0, file_type="pdf"):
        return SampleManifestEntry(
            list_id=list_id,
            segment_index=seg_idx,
            source_file=source_file,
            file_type=file_type,
            char_count=200,
        )

    def test_returns_request_per_sample(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import prepare_parse_requests

        sample = self._make_sample(str(tmp_path / "list.pdf"))
        taxonomy = TaxonomyResult(
            status="OK",
            categories=[TaxonomyNode(name="Champagne", subcategories=[])],
        )
        taxonomies = {"list1": taxonomy}

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="some wine text"):
            reqs = prepare_parse_requests([sample], taxonomies, sft_settings, progress)

        assert len(reqs) == 1
        assert reqs[0].custom_id == "parse__list1__0"
        assert reqs[0].model == sft_settings.teacher_model
        assert reqs[0].response_format == {"type": "json_object"}

    def test_injects_taxonomy_in_user_message(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import prepare_parse_requests

        sample = self._make_sample(str(tmp_path / "list.pdf"))
        taxonomy = TaxonomyResult(
            status="OK",
            categories=[TaxonomyNode(name="Burgundy White", subcategories=[])],
        )
        taxonomies = {"list1": taxonomy}

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="wine text"):
            reqs = prepare_parse_requests([sample], taxonomies, sft_settings, progress)

        # User message content should contain the taxonomy category name
        user_content = reqs[0].messages[1]["content"]
        text = user_content if isinstance(user_content, str) else user_content[0].get("text", "")
        assert "Burgundy White" in text

    def test_adds_cache_points_for_anthropic_model(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import prepare_parse_requests

        settings = sft_settings.__class__(
            data_dir=str(sft_settings.data_path),
            teacher_model="claude-opus-4-5",
        )
        sample = self._make_sample(str(tmp_path / "list.pdf"))

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="wine text"):
            reqs = prepare_parse_requests([sample], {}, settings, progress)

        assert reqs[0].cache_control_injection_points is not None

    def test_no_cache_points_for_openai_model(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import prepare_parse_requests

        settings = sft_settings.__class__(
            data_dir=str(sft_settings.data_path),
            teacher_model="gpt-4o",
        )
        sample = self._make_sample(str(tmp_path / "list.pdf"))

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="wine text"):
            reqs = prepare_parse_requests([sample], {}, settings, progress)

        assert reqs[0].cache_control_injection_points is None

    def test_skips_already_parsed_segments(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import prepare_parse_requests

        sample = self._make_sample(str(tmp_path / "list.pdf"))
        progress.mark_parse_done("list1", 0)

        reqs = prepare_parse_requests([sample], {}, sft_settings, progress)
        assert reqs == []


class TestProcessParseResponses:
    def _make_sample(self, source_file, list_id="list1", seg_idx=0):
        return SampleManifestEntry(
            list_id=list_id, segment_index=seg_idx,
            source_file=source_file, file_type="pdf",
            char_count=200,
        )

    def test_processes_valid_wines(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import process_parse_responses

        sft_settings.parsed_dir.mkdir(parents=True, exist_ok=True)
        sft_settings.taxonomy_dir.mkdir(parents=True, exist_ok=True)
        sample = self._make_sample(str(tmp_path / "f.pdf"))
        samples_by_id = {"parse__list1__0": sample}

        response = LLMResponse(
            custom_id="parse__list1__0",
            content=json.dumps({"wines": [{"name": "Krug", "price": 350}]}),
            tokens={"input": 500, "output": 100, "cached": 400},
        )

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="segment text"), \
             patch("winerank.sft.wine_parser.load_taxonomy", return_value=None):
            results = process_parse_responses([response], samples_by_id, sft_settings, progress)

        assert len(results) == 1
        assert len(results[0].wines) == 1
        assert results[0].wines[0].name == "Krug"
        assert results[0].cached_tokens == 400

    def test_handles_executor_error(self, tmp_path, sft_settings, progress):
        from winerank.sft.wine_parser import process_parse_responses

        sft_settings.parsed_dir.mkdir(parents=True, exist_ok=True)
        sft_settings.taxonomy_dir.mkdir(parents=True, exist_ok=True)
        sample = self._make_sample(str(tmp_path / "f.pdf"))
        samples_by_id = {"parse__list1__0": sample}

        response = LLMResponse(
            custom_id="parse__list1__0",
            content="",
            tokens={"input": 0, "output": 0, "cached": 0},
            error="Timeout",
        )

        with patch("winerank.sft.wine_parser._get_segment_text", return_value="text"), \
             patch("winerank.sft.wine_parser.load_taxonomy", return_value=None):
            results = process_parse_responses([response], samples_by_id, sft_settings, progress)

        assert len(results) == 1
        assert results[0].parse_error == "Timeout"
        assert results[0].wines == []


# ---------------------------------------------------------------------------
# Judge prepare
# ---------------------------------------------------------------------------

class TestPrepareJudgeRequests:
    def _make_parse_result(self, list_id="list1", seg_idx=0, has_error=False):
        wines = [] if has_error else [WineEntry(name="Wine A", price=50)]
        return PageParseResult(
            segment_id=f"{list_id}__{seg_idx}",
            list_id=list_id,
            segment_index=seg_idx,
            source_file="/tmp/f.pdf",
            segment_text="some wines here",
            taxonomy_text="Red Wine\nWhite Wine",
            wines=wines,
            parse_error="error" if has_error else None,
        )

    def test_returns_request_per_parse_result(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import prepare_judge_requests

        results = [self._make_parse_result(seg_idx=i) for i in range(3)]
        reqs = prepare_judge_requests(results, sft_settings, progress)

        assert len(reqs) == 3
        for i, req in enumerate(reqs):
            assert req.custom_id == f"judge__list1__{i}"
            assert req.model == sft_settings.judge_model

    def test_skips_segments_with_parse_errors(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import prepare_judge_requests

        results = [
            self._make_parse_result(seg_idx=0, has_error=False),
            self._make_parse_result(seg_idx=1, has_error=True),
        ]
        reqs = prepare_judge_requests(results, sft_settings, progress)
        assert len(reqs) == 1
        assert reqs[0].custom_id == "judge__list1__0"

    def test_skips_already_judged_segments(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import prepare_judge_requests

        results = [self._make_parse_result()]
        progress.mark_judge_done("list1", 0)

        reqs = prepare_judge_requests(results, sft_settings, progress)
        assert reqs == []

    def test_includes_segment_text_and_parsed_json(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import prepare_judge_requests

        result = self._make_parse_result()
        reqs = prepare_judge_requests([result], sft_settings, progress)

        user_content = reqs[0].messages[1]["content"]
        if isinstance(user_content, list):
            text = " ".join(block.get("text", "") for block in user_content if isinstance(block, dict))
        else:
            text = user_content
        assert "some wines here" in text
        assert "Wine A" in text


class TestProcessJudgeResponses:
    def test_processes_valid_judge_response(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import process_judge_responses

        sft_settings.judged_dir.mkdir(parents=True, exist_ok=True)
        response = LLMResponse(
            custom_id="judge__list1__0",
            content=json.dumps({
                "score": 0.95,
                "wine_count_match": True,
                "issues": [],
                "recommendation": "accept",
            }),
            tokens={"input": 200, "output": 60, "cached": 0},
        )

        results = process_judge_responses([response], sft_settings, progress)

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.95)
        assert results[0].recommendation == "accept"
        assert results[0].wine_count_match is True

    def test_handles_executor_error(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import process_judge_responses

        sft_settings.judged_dir.mkdir(parents=True, exist_ok=True)
        response = LLMResponse(
            custom_id="judge__list1__0",
            content="",
            tokens={"input": 0, "output": 0, "cached": 0},
            error="API error",
        )
        results = process_judge_responses([response], sft_settings, progress)
        assert results == []

    def test_saves_to_disk(self, sft_settings, progress):
        from winerank.sft.judge_reviewer import load_judge_result, process_judge_responses

        sft_settings.judged_dir.mkdir(parents=True, exist_ok=True)
        response = LLMResponse(
            custom_id="judge__list1__2",
            content=json.dumps({
                "score": 0.7,
                "wine_count_match": False,
                "issues": [
                    {"type": "other", "description": "Missing vintage"},
                ],
                "recommendation": "review",
            }),
            tokens={"input": 200, "output": 60, "cached": 0},
        )
        process_judge_responses([response], sft_settings, progress)

        loaded = load_judge_result(sft_settings.judged_dir, "list1", 2)
        assert loaded is not None
        assert loaded.recommendation == "review"
