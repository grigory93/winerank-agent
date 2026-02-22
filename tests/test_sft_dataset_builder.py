"""Tests for dataset builder: JSONL assembly and metadata."""
import json
from pathlib import Path

import pytest

from winerank.sft.dataset_builder import build_dataset, load_dataset_metadata
from winerank.sft.judge_reviewer import save_judge_result
from winerank.sft.schemas import JudgeResult, PageParseResult, WineEntry
from winerank.sft.wine_parser import save_parse_result


@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(
        data_dir=str(tmp_path / "sft"),
        teacher_model="claude-opus-4-5",
        taxonomy_model="gpt-4o-mini",
        num_samples=10,
        seed=42,
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


def _make_parse_result(list_id: str, seg_idx: int, num_wines: int = 2) -> PageParseResult:
    wines = [WineEntry(name=f"Wine {i}", price=100.0 * i) for i in range(num_wines)]
    return PageParseResult(
        segment_id=f"{list_id}__{seg_idx}",
        list_id=list_id,
        segment_index=seg_idx,
        source_file=f"data/examples/{list_id}.pdf",
        segment_text=f"Text for segment {seg_idx}",
        taxonomy_text="Champagne\nRed Wines",
        wines=wines,
        model_used="claude-opus-4-5",
        input_tokens=200,
        output_tokens=100,
    )


def _make_judge_result(segment_id: str, score: float, recommendation: str) -> JudgeResult:
    parts = segment_id.rsplit("__", 1)
    list_id, seg_idx = parts[0], int(parts[1])
    return JudgeResult(
        segment_id=segment_id,
        list_id=list_id,
        segment_index=seg_idx,
        score=score,
        wine_count_match=True,
        issues=[],
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# build_dataset
# ---------------------------------------------------------------------------


def test_build_dataset_basic(sft_settings, progress):
    sft_settings.ensure_dirs()

    # Create 3 parse results
    for i in range(3):
        r = _make_parse_result("list1", i)
        save_parse_result(r, sft_settings.parsed_dir)

    jsonl_path = build_dataset(sft_settings, progress)

    assert jsonl_path.exists()
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 3

    # Each line should be valid JSON with "messages"
    for line in lines:
        sample = json.loads(line)
        assert "messages" in sample
        messages = sample["messages"]
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"


def test_build_dataset_messages_content(sft_settings, progress):
    sft_settings.ensure_dirs()
    r = _make_parse_result("list1", 0, num_wines=1)
    save_parse_result(r, sft_settings.parsed_dir)

    jsonl_path = build_dataset(sft_settings, progress)
    line = json.loads(jsonl_path.read_text().strip())

    system_msg = line["messages"][0]["content"]
    user_msg = line["messages"][1]["content"]
    assistant_msg = line["messages"][2]["content"]

    # System prompt should contain schema
    assert "varietal" in system_msg
    # User message should contain taxonomy and segment text
    assert "Champagne" in user_msg
    assert "Text for segment 0" in user_msg
    # Assistant should contain wine JSON
    parsed = json.loads(assistant_msg)
    assert "wines" in parsed
    assert len(parsed["wines"]) == 1


def test_build_dataset_skips_parse_errors(sft_settings, progress):
    sft_settings.ensure_dirs()

    r_good = _make_parse_result("list1", 0)
    r_bad = PageParseResult(
        segment_id="list1__1",
        list_id="list1",
        segment_index=1,
        source_file="test.pdf",
        segment_text="bad segment",
        taxonomy_text="taxonomy",
        wines=[],
        parse_error="JSON parse error",
    )
    save_parse_result(r_good, sft_settings.parsed_dir)
    save_parse_result(r_bad, sft_settings.parsed_dir)

    jsonl_path = build_dataset(sft_settings, progress)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_build_dataset_skips_empty_wines(sft_settings, progress):
    sft_settings.ensure_dirs()

    r_wines = _make_parse_result("list1", 0, num_wines=2)
    r_empty = PageParseResult(
        segment_id="list1__1",
        list_id="list1",
        segment_index=1,
        source_file="test.pdf",
        segment_text="empty segment",
        taxonomy_text="taxonomy",
        wines=[],
    )
    save_parse_result(r_wines, sft_settings.parsed_dir)
    save_parse_result(r_empty, sft_settings.parsed_dir)

    jsonl_path = build_dataset(sft_settings, progress)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_build_dataset_judge_filtering(sft_settings, progress):
    sft_settings.ensure_dirs()

    for i in range(4):
        r = _make_parse_result("list1", i)
        save_parse_result(r, sft_settings.parsed_dir)

    # 2 accept, 2 reject
    save_judge_result(_make_judge_result("list1__0", 0.95, "accept"), sft_settings.judged_dir)
    save_judge_result(_make_judge_result("list1__1", 0.9, "accept"), sft_settings.judged_dir)
    save_judge_result(_make_judge_result("list1__2", 0.3, "reject"), sft_settings.judged_dir)
    save_judge_result(_make_judge_result("list1__3", 0.2, "reject"), sft_settings.judged_dir)

    jsonl_path = build_dataset(sft_settings, progress, min_judge_score=0.7)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 2


def test_build_dataset_no_judge_includes_all(sft_settings, progress):
    sft_settings.ensure_dirs()

    for i in range(3):
        r = _make_parse_result("list1", i)
        save_parse_result(r, sft_settings.parsed_dir)

    # No judge results, no min score filter
    jsonl_path = build_dataset(sft_settings, progress, min_judge_score=0.0)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 3


def test_build_dataset_metadata_created(sft_settings, progress):
    sft_settings.ensure_dirs()
    r = _make_parse_result("list1", 0)
    save_parse_result(r, sft_settings.parsed_dir)

    build_dataset(sft_settings, progress)

    meta = load_dataset_metadata(sft_settings.dataset_dir)
    assert meta is not None
    assert meta.teacher_model == "claude-opus-4-5"
    assert meta.taxonomy_model == "gpt-4o-mini"
    assert meta.num_samples_actual == 1
    assert meta.generated_at != ""


def test_build_dataset_empty(sft_settings, progress):
    sft_settings.ensure_dirs()
    # No parse results at all
    jsonl_path = build_dataset(sft_settings, progress)
    # File should exist but be empty
    content = jsonl_path.read_text().strip()
    assert content == ""

    meta = load_dataset_metadata(sft_settings.dataset_dir)
    assert meta is not None
    assert meta.num_samples_actual == 0
