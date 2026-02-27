"""Tests for the corrector module (LLM calls mocked)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.corrector import (
    prepare_correction_requests,
    process_correction_responses,
)
from winerank.sft.executor.types import LLMResponse
from winerank.sft.schemas import (
    JudgeIssue,
    JudgeResult,
    PageParseResult,
    TaxonomyNode,
    TaxonomyResult,
    WineEntry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CORRECTED_RESPONSE = json.dumps({
    "wines": [
        {
            "name": "Krug Grande Cuvee",
            "winery": "Krug",
            "wine_type": "Sparkling",
            "country": "France",
            "region": "Champagne",
            "price": 450.0,
            "vintage": "NV",
        },
        {
            "name": "Dom Perignon",
            "winery": "Moet & Chandon",
            "wine_type": "Sparkling",
            "country": "France",
            "price": 300.0,
            "vintage": "2015",
        },
    ]
})


@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(
        data_dir=str(tmp_path / "sft"),
        teacher_model="claude-opus-4-5",
        judge_model="claude-opus-4-5",
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


@pytest.fixture
def taxonomy():
    return TaxonomyResult(
        status="OK",
        restaurant_name="Test Restaurant",
        categories=[TaxonomyNode(name="Champagne")],
    )


@pytest.fixture
def parse_result_review():
    """A parse result that needs correction (missing a wine)."""
    return PageParseResult(
        segment_id="test-list__0",
        list_id="test-list",
        segment_index=0,
        source_file="test.pdf",
        segment_text="Champagne\nKrug Grande Cuvee NV $450\nDom Perignon 2015 $300",
        taxonomy_text="Champagne",
        wines=[WineEntry(name="Krug Grande Cuvee", price=450.0, vintage="NV")],
        model_used="claude-opus-4-5",
    )


@pytest.fixture
def judge_result_review():
    return JudgeResult(
        segment_id="test-list__0",
        list_id="test-list",
        segment_index=0,
        score=0.6,
        wine_count_match=False,
        issues=[
            JudgeIssue(
                type="missing_wine",
                description="Dom Perignon 2015 at $300 not extracted",
                wine_name="Dom Perignon",
            )
        ],
        recommendation="review",
        needs_reparse=True,
    )


@pytest.fixture
def judge_result_accept():
    return JudgeResult(
        segment_id="test-list__1",
        list_id="test-list",
        segment_index=1,
        score=0.95,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
        needs_reparse=False,
    )


# ---------------------------------------------------------------------------
# prepare_correction_requests
# ---------------------------------------------------------------------------


def test_prepare_correction_only_includes_flagged(
    parse_result_review, judge_result_review, judge_result_accept, taxonomy, sft_settings, progress
):
    parse_result_accept = PageParseResult(
        segment_id="test-list__1",
        list_id="test-list",
        segment_index=1,
        source_file="test.pdf",
        segment_text="Red wines text",
        taxonomy_text="Red",
        wines=[WineEntry(name="Opus One", price=500.0)],
        model_used="claude-opus-4-5",
    )

    requests = prepare_correction_requests(
        parse_results=[parse_result_review, parse_result_accept],
        judge_results={
            "test-list__0": judge_result_review,
            "test-list__1": judge_result_accept,
        },
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    assert len(requests) == 1
    assert requests[0].custom_id == "correct__test-list__0__1"


def test_prepare_correction_skips_no_judge(
    parse_result_review, taxonomy, sft_settings, progress
):
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )
    assert requests == []


def test_prepare_correction_includes_judge_issues_in_prompt(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    assert len(requests) == 1
    req = requests[0]
    user_msg = next(m for m in req.messages if m["role"] == "user")
    content = user_msg["content"]
    # Content may be a list of blocks or a string
    if isinstance(content, list):
        content = " ".join(block.get("text", "") for block in content)
    assert "Dom Perignon" in content
    assert "missing_wine" in content.lower() or "MISSING_WINE" in content


def test_prepare_correction_includes_previous_json(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    req = requests[0]
    user_msg = next(m for m in req.messages if m["role"] == "user")
    content = user_msg["content"]
    if isinstance(content, list):
        content = " ".join(block.get("text", "") for block in content)
    # Previous JSON includes the wine from the original parse
    assert "Krug Grande Cuvee" in content


def test_prepare_correction_uses_wine_parsing_system_prompt(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    from winerank.sft.prompts import WINE_PARSING_SYSTEM_PROMPT

    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    sys_msg = next(m for m in requests[0].messages if m["role"] == "system")
    assert sys_msg["content"] == WINE_PARSING_SYSTEM_PROMPT


def test_prepare_correction_anthropic_cache_points(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    settings = sft_settings
    # claude model -> should include cache_control_injection_points
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=settings,
        progress=progress,
        round_num=1,
    )
    assert requests[0].cache_control_injection_points is not None


def test_prepare_correction_skips_if_done(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    progress.mark_correction_done("test-list", 0, round_num=1)
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )
    assert requests == []


def test_prepare_correction_force_reruns_done(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    progress.mark_correction_done("test-list", 0, round_num=1)
    requests = prepare_correction_requests(
        parse_results=[parse_result_review],
        judge_results={"test-list__0": judge_result_review},
        taxonomies={"test-list": taxonomy},
        settings=sft_settings,
        progress=progress,
        round_num=1,
        force=True,
    )
    assert len(requests) == 1


def test_prepare_correction_round_num_in_custom_id(
    parse_result_review, judge_result_review, taxonomy, sft_settings, progress
):
    for round_num in (1, 2):
        requests = prepare_correction_requests(
            parse_results=[parse_result_review],
            judge_results={"test-list__0": judge_result_review},
            taxonomies={"test-list": taxonomy},
            settings=sft_settings,
            progress=progress,
            round_num=round_num,
            force=True,
        )
        assert f"__{round_num}" in requests[0].custom_id


# ---------------------------------------------------------------------------
# process_correction_responses
# ---------------------------------------------------------------------------


def _make_llm_response(custom_id: str, content: str, error: str | None = None):
    return LLMResponse(
        custom_id=custom_id,
        content=content,
        tokens={"input": 500, "output": 100, "cached": 200},
        error=error,
    )


def test_process_correction_overwrites_parsed_result(
    parse_result_review, sft_settings, progress
):
    sft_settings.ensure_dirs()
    # Save original parse result
    from winerank.sft.wine_parser import save_parse_result
    save_parse_result(parse_result_review, sft_settings.parsed_dir)

    response = _make_llm_response("correct__test-list__0__1", CORRECTED_RESPONSE)
    corrected = process_correction_responses(
        responses=[response],
        parse_results_by_id={"test-list__0": parse_result_review},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    assert len(corrected) == 1
    result = corrected[0]
    assert result.correction_round == 1
    assert len(result.wines) == 2

    # Verify file was overwritten on disk
    from winerank.sft.wine_parser import load_parse_result
    loaded = load_parse_result(sft_settings.parsed_dir, "test-list", 0)
    assert loaded is not None
    assert loaded.correction_round == 1
    assert len(loaded.wines) == 2


def test_process_correction_tracks_progress(parse_result_review, sft_settings, progress):
    sft_settings.ensure_dirs()

    response = _make_llm_response("correct__test-list__0__1", CORRECTED_RESPONSE)
    process_correction_responses(
        responses=[response],
        parse_results_by_id={"test-list__0": parse_result_review},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    assert progress.is_correction_done("test-list", 0, round_num=1)


def test_process_correction_handles_error_response(parse_result_review, sft_settings, progress):
    sft_settings.ensure_dirs()

    response = _make_llm_response("correct__test-list__0__1", "", error="API error")
    corrected = process_correction_responses(
        responses=[response],
        parse_results_by_id={"test-list__0": parse_result_review},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )
    assert corrected == []
    assert not progress.is_correction_done("test-list", 0, round_num=1)


def test_process_correction_handles_invalid_json(parse_result_review, sft_settings, progress):
    sft_settings.ensure_dirs()

    response = _make_llm_response("correct__test-list__0__1", "not valid json at all")
    corrected = process_correction_responses(
        responses=[response],
        parse_results_by_id={"test-list__0": parse_result_review},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )
    assert len(corrected) == 1
    assert corrected[0].parse_error is not None
    assert corrected[0].wines == []


def test_process_correction_preserves_original_metadata(parse_result_review, sft_settings, progress):
    sft_settings.ensure_dirs()

    response = _make_llm_response("correct__test-list__0__1", CORRECTED_RESPONSE)
    corrected = process_correction_responses(
        responses=[response],
        parse_results_by_id={"test-list__0": parse_result_review},
        settings=sft_settings,
        progress=progress,
        round_num=1,
    )

    assert corrected[0].segment_text == parse_result_review.segment_text
    assert corrected[0].taxonomy_text == parse_result_review.taxonomy_text
    assert corrected[0].source_file == parse_result_review.source_file
