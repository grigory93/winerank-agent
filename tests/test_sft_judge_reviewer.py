"""Tests for judge reviewer (LLM calls mocked)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.judge_reviewer import (
    judge_all_segments,
    load_all_judge_results,
    load_judge_result,
    save_judge_result,
)
from winerank.sft.schemas import JudgeIssue, JudgeResult, PageParseResult, WineEntry


JUDGE_RESPONSE = json.dumps({
    "score": 0.95,
    "wine_count_match": True,
    "issues": [],
    "needs_reparse": False,
    "recommendation": "accept",
})

JUDGE_RESPONSE_ISSUES = json.dumps({
    "score": 0.6,
    "wine_count_match": False,
    "issues": [
        {
            "type": "missing_wine",
            "description": "Missing wine: Chateau Margaux",
            "wine_name": "Chateau Margaux",
        },
        {
            "type": "wrong_price",
            "description": "Price incorrect for Dom Perignon",
            "wine_name": "Dom Perignon",
            "field": "price",
            "current_value": "850",
            "expected_value": "85",
        },
    ],
    "needs_reparse": True,
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
        training_data_mode="text",
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


def _make_litellm_response(content: str):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage = MagicMock()
    mock_resp.usage.prompt_tokens = 300
    mock_resp.usage.completion_tokens = 50
    mock_resp.usage.cache_read_input_tokens = 0
    mock_resp.usage.prompt_tokens_details = None
    return mock_resp


# ---------------------------------------------------------------------------
# judge_all_segments (uses SyncExecutor -- LLM mocked at litellm level)
# ---------------------------------------------------------------------------


def test_judge_all_segments_ok(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response(JUDGE_RESPONSE)
        results = judge_all_segments([parse_result], sft_settings, progress)

    assert len(results) == 1
    assert results[0].score == 0.95
    assert results[0].recommendation == "accept"
    assert results[0].wine_count_match is True
    assert results[0].issues == []


def test_judge_all_segments_with_issues(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response(JUDGE_RESPONSE_ISSUES)
        results = judge_all_segments([parse_result], sft_settings, progress)

    assert results[0].score == 0.6
    assert results[0].recommendation == "review"
    assert len(results[0].issues) == 2
    assert results[0].needs_reparse is True
    # Issues are structured JudgeIssue objects
    issue_types = {i.type for i in results[0].issues}
    assert "missing_wine" in issue_types
    assert "wrong_price" in issue_types


def test_judge_all_segments_original_text_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_completion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_litellm_response(JUDGE_RESPONSE)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = fake_completion
        judge_all_segments([parse_result], sft_settings, progress)

    user_msg = next(m for m in captured_messages[0] if m["role"] == "user")
    content = user_msg["content"]
    if isinstance(content, list):
        text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
    else:
        text = content
    assert "Krug NV $450" in text


def test_judge_all_segments_taxonomy_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_completion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_litellm_response(JUDGE_RESPONSE)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = fake_completion
        judge_all_segments([parse_result], sft_settings, progress)

    user_msg = next(m for m in captured_messages[0] if m["role"] == "user")
    content = user_msg["content"]
    if isinstance(content, list):
        text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
    else:
        text = content
    assert "Champagne" in text


def test_judge_all_segments_parsed_json_in_prompt(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_completion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_litellm_response(JUDGE_RESPONSE)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = fake_completion
        judge_all_segments([parse_result], sft_settings, progress)

    user_msg = next(m for m in captured_messages[0] if m["role"] == "user")
    content = user_msg["content"]
    if isinstance(content, list):
        text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
    else:
        text = content
    assert "Krug Grande Cuvee" in text


def test_judge_all_segments_skips_if_done(parse_result, sft_settings, progress):
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

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        judge_all_segments([parse_result], sft_settings, progress)

    mock_litellm.completion.assert_not_called()


def test_judge_all_segments_skips_parse_errors(sft_settings, progress):
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
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        results = judge_all_segments([errored_result], sft_settings, progress)

    mock_litellm.completion.assert_not_called()
    assert results == []


def test_judge_all_segments_dry_run(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        results = judge_all_segments([parse_result], sft_settings, progress, dry_run=True)

    mock_litellm.completion.assert_not_called()
    assert results == []


def test_judge_all_segments_handles_model_error(parse_result, sft_settings, progress):
    sft_settings.ensure_dirs()
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = Exception("API failure")
        results = judge_all_segments([parse_result], sft_settings, progress)

    assert results == []


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
        issues=[
            JudgeIssue(type="wrong_attribute", description="Minor: appellation missing",
                       wine_name="Opus One", field="appellation")
        ],
        recommendation="accept",
        needs_reparse=False,
        model_used="claude-opus-4-5",
    )
    save_judge_result(result, tmp_path)
    loaded = load_judge_result(tmp_path, "list1", 0)
    assert loaded is not None
    assert loaded.score == 0.85
    assert loaded.issues[0].type == "wrong_attribute"
    assert loaded.issues[0].wine_name == "Opus One"
    assert loaded.needs_reparse is False


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
