"""Tests for judge reviewer (LLM calls mocked)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.judge_reviewer import (
    judge_segment,
    load_all_judge_results,
    load_judge_result,
    save_judge_result,
)
from winerank.sft.schemas import JudgeResult, PageParseResult, WineEntry


JUDGE_RESPONSE = json.dumps({
    "score": 0.95,
    "wine_count_match": True,
    "issues": [],
    "recommendation": "accept",
})

JUDGE_RESPONSE_ISSUES = json.dumps({
    "score": 0.6,
    "wine_count_match": False,
    "issues": ["Missing wine: Chateau Margaux", "Price incorrect for Dom Perignon"],
    "recommendation": "review",
})


@pytest.fixture
def parse_result(tmp_path):
    html = tmp_path / "wine.html"
    html.write_text("<html><body><h2>Champagne</h2><p>Krug NV $450</p></body></html>")
    return PageParseResult(
        segment_id="test-list__2",
        list_id="test-list",
        segment_index=2,
        source_file=str(html),
        segment_text="Champagne\nKrug NV $450",
        taxonomy_text="Champagne",
        wines=[WineEntry(name="Krug Grande Cuvee", price=450.0, vintage="NV")],
        model_used="claude-opus-4-5",
    )


@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(
        data_dir=str(tmp_path / "sft"),
        judge_model="claude-opus-4-5",
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


# ---------------------------------------------------------------------------
# judge_segment
# ---------------------------------------------------------------------------


def test_judge_segment_ok(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()

    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        mock_call.return_value = (JUDGE_RESPONSE, {"input": 300, "output": 50, "cached": 0})
        result = judge_segment(parse_result, sft_settings, progress)

    assert result is not None
    assert result.score == 0.95
    assert result.recommendation == "accept"
    assert result.wine_count_match is True
    assert result.issues == []


def test_judge_segment_with_issues(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()

    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        mock_call.return_value = (JUDGE_RESPONSE_ISSUES, {"input": 300, "output": 80, "cached": 0})
        result = judge_segment(parse_result, sft_settings, progress)

    assert result is not None
    assert result.score == 0.6
    assert result.recommendation == "review"
    assert len(result.issues) == 2


def test_judge_segment_original_text_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_call(messages, model, **kwargs):
        captured_messages.extend(messages)
        return (JUDGE_RESPONSE, {"input": 300, "output": 50, "cached": 0})

    with patch("winerank.sft.judge_reviewer._call_judge_model", side_effect=fake_call):
        judge_segment(parse_result, sft_settings, progress)

    user_msg = next(m for m in captured_messages if m["role"] == "user")
    assert "Krug NV $450" in user_msg["content"]


def test_judge_segment_taxonomy_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_call(messages, model, **kwargs):
        captured_messages.extend(messages)
        return (JUDGE_RESPONSE, {"input": 300, "output": 50, "cached": 0})

    with patch("winerank.sft.judge_reviewer._call_judge_model", side_effect=fake_call):
        judge_segment(parse_result, sft_settings, progress)

    user_msg = next(m for m in captured_messages if m["role"] == "user")
    assert "Champagne" in user_msg["content"]


def test_judge_segment_parsed_json_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_call(messages, model, **kwargs):
        captured_messages.extend(messages)
        return (JUDGE_RESPONSE, {"input": 300, "output": 50, "cached": 0})

    with patch("winerank.sft.judge_reviewer._call_judge_model", side_effect=fake_call):
        judge_segment(parse_result, sft_settings, progress)

    user_msg = next(m for m in captured_messages if m["role"] == "user")
    assert "Krug Grande Cuvee" in user_msg["content"]


def test_judge_segment_skips_if_done(parse_result, sft_settings, progress, tmp_path):
    sft_settings.ensure_dirs()
    existing = JudgeResult(
        segment_id="test-list__2",
        list_id="test-list",
        segment_index=2,
        score=0.9,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
    )
    save_judge_result(existing, sft_settings.judged_dir)
    progress.mark_judge_done("test-list", 2)

    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        result = judge_segment(parse_result, sft_settings, progress)

    mock_call.assert_not_called()


def test_judge_segment_skips_parse_errors(sft_settings, progress):
    sft_settings.ensure_dirs()
    errored_result = PageParseResult(
        segment_id="test-list__3",
        list_id="test-list",
        segment_index=3,
        source_file="test.pdf",
        segment_text="text",
        taxonomy_text="taxonomy",
        wines=[],
        parse_error="Model returned invalid JSON",
    )
    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        result = judge_segment(errored_result, sft_settings, progress)

    mock_call.assert_not_called()
    assert result is None


def test_judge_segment_dry_run(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        result = judge_segment(parse_result, sft_settings, progress, dry_run=True)

    mock_call.assert_not_called()
    assert result is None


def test_judge_segment_handles_model_error(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    with patch("winerank.sft.judge_reviewer._call_judge_model") as mock_call:
        mock_call.side_effect = Exception("API failure")
        result = judge_segment(parse_result, sft_settings, progress)

    assert result is None
    assert progress.is_judge_done("test-list", 2) is False


# ---------------------------------------------------------------------------
# save_judge_result / load_judge_result round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_judge_result(tmp_path):
    result = JudgeResult(
        segment_id="list1__0",
        list_id="list1",
        segment_index=0,
        score=0.85,
        wine_count_match=True,
        issues=["Minor: appellation missing"],
        recommendation="accept",
        model_used="claude-opus-4-5",
    )
    save_judge_result(result, tmp_path)
    loaded = load_judge_result(tmp_path, "list1", 0)
    assert loaded is not None
    assert loaded.score == 0.85
    assert loaded.issues[0] == "Minor: appellation missing"


def test_load_judge_result_not_found(tmp_path):
    assert load_judge_result(tmp_path, "nonexistent", 0) is None


def test_load_all_judge_results(tmp_path):
    for i in range(3):
        r = JudgeResult(
            segment_id=f"list1__{i}",
            list_id="list1",
            segment_index=i,
            score=0.9 - i * 0.1,
            wine_count_match=True,
            issues=[],
            recommendation="accept",
        )
        save_judge_result(r, tmp_path)

    all_results = load_all_judge_results(tmp_path)
    assert len(all_results) == 3
    assert "list1__0" in all_results
