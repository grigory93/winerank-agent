"""Tests for SFT progress tracking."""
import json
from pathlib import Path

import pytest

from winerank.sft.progress import ProgressTracker


@pytest.fixture
def tracker(tmp_path):
    return ProgressTracker(tmp_path / "progress.json")


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def test_mark_taxonomy_done(tracker):
    assert not tracker.is_taxonomy_done("list1")
    tracker.mark_taxonomy_done("list1", "OK", tokens={"input": 100, "output": 50})
    assert tracker.is_taxonomy_done("list1")
    assert tracker.get_taxonomy_status("list1") == "OK"


def test_mark_taxonomy_not_a_list(tracker):
    tracker.mark_taxonomy_done("list2", "NOT_A_LIST")
    assert tracker.is_taxonomy_done("list2")
    assert tracker.get_taxonomy_status("list2") == "NOT_A_LIST"


def test_taxonomy_error_not_done(tracker):
    tracker.mark_taxonomy_done("list3", "ERROR", error="Something went wrong")
    # ERROR status should NOT count as done (don't skip retrying errors)
    assert not tracker.is_taxonomy_done("list3")


def test_get_not_a_list_ids(tracker):
    tracker.mark_taxonomy_done("list1", "OK")
    tracker.mark_taxonomy_done("list2", "NOT_A_LIST")
    tracker.mark_taxonomy_done("list3", "NOT_A_LIST")
    tracker.mark_taxonomy_done("list4", "ERROR")

    not_a_list = tracker.get_not_a_list_ids()
    assert not_a_list == {"list2", "list3"}


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_mark_parse_done(tracker):
    assert not tracker.is_parse_done("list1", 0)
    tracker.mark_parse_done("list1", 0, tokens={"input": 200, "output": 100})
    assert tracker.is_parse_done("list1", 0)


def test_parse_error_not_done(tracker):
    tracker.mark_parse_done("list1", 0, error="JSON error")
    assert not tracker.is_parse_done("list1", 0)


def test_parse_different_segments_independent(tracker):
    tracker.mark_parse_done("list1", 0)
    assert not tracker.is_parse_done("list1", 1)
    assert not tracker.is_parse_done("list2", 0)


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


def test_mark_judge_done(tracker):
    assert not tracker.is_judge_done("list1", 0)
    tracker.mark_judge_done("list1", 0, tokens={"input": 150, "output": 60})
    assert tracker.is_judge_done("list1", 0)


def test_judge_error_not_done(tracker):
    tracker.mark_judge_done("list1", 0, error="Model error")
    assert not tracker.is_judge_done("list1", 0)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_and_reload(tmp_path):
    tracker = ProgressTracker(tmp_path / "progress.json")
    tracker.mark_taxonomy_done("list1", "OK", tokens={"input": 100, "output": 50})
    tracker.mark_parse_done("list1", 0, tokens={"input": 200, "output": 100})

    # Reload from disk
    tracker2 = ProgressTracker(tmp_path / "progress.json")
    assert tracker2.is_taxonomy_done("list1")
    assert tracker2.is_parse_done("list1", 0)


def test_corrupted_file_starts_fresh(tmp_path):
    progress_file = tmp_path / "progress.json"
    progress_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
    tracker = ProgressTracker(progress_file)
    # Should not raise, should start with empty state
    assert not tracker.is_taxonomy_done("list1")


def test_missing_file_starts_fresh(tmp_path):
    tracker = ProgressTracker(tmp_path / "nonexistent.json")
    assert not tracker.is_taxonomy_done("list1")


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_clears_all(tracker):
    tracker.mark_taxonomy_done("list1", "OK")
    tracker.mark_parse_done("list1", 0)
    tracker.mark_judge_done("list1", 0)
    tracker.reset()

    assert not tracker.is_taxonomy_done("list1")
    assert not tracker.is_parse_done("list1", 0)
    assert not tracker.is_judge_done("list1", 0)


# ---------------------------------------------------------------------------
# Summary & token stats
# ---------------------------------------------------------------------------


def test_summary(tracker):
    tracker.mark_taxonomy_done("list1", "OK", tokens={"input": 100, "output": 50, "cached": 10})
    tracker.mark_taxonomy_done("list2", "NOT_A_LIST")
    tracker.mark_taxonomy_done("list3", "ERROR")
    tracker.mark_parse_done("list1", 0)
    tracker.mark_parse_done("list1", 1, error="err")
    tracker.mark_judge_done("list1", 0)

    summary = tracker.summary()
    assert summary["taxonomy"]["ok"] == 1
    assert summary["taxonomy"]["not_a_list"] == 1
    assert summary["taxonomy"]["error"] == 1
    assert summary["taxonomy"]["total"] == 3
    assert summary["parse"]["ok"] == 1
    assert summary["parse"]["error"] == 1
    assert summary["judge"]["ok"] == 1


def test_total_tokens(tracker):
    tracker.mark_taxonomy_done("list1", "OK", tokens={"input": 100, "output": 50, "cached": 10})
    tracker.mark_parse_done("list1", 0, tokens={"input": 200, "output": 100, "cached": 50})
    tracker.mark_judge_done("list1", 0, tokens={"input": 150, "output": 60, "cached": 0})

    tokens = tracker.total_tokens()
    assert tokens["input"] == 450
    assert tokens["output"] == 210
    assert tokens["cached"] == 60


# ---------------------------------------------------------------------------
# Correction
# ---------------------------------------------------------------------------


def test_mark_correction_done(tracker):
    assert not tracker.is_correction_done("list1", 0, round_num=1)
    tracker.mark_correction_done("list1", 0, round_num=1, tokens={"input": 300, "output": 80})
    assert tracker.is_correction_done("list1", 0, round_num=1)


def test_correction_error_not_done(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1, error="API failure")
    assert not tracker.is_correction_done("list1", 0, round_num=1)


def test_correction_separate_rounds(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1)
    assert tracker.is_correction_done("list1", 0, round_num=1)
    assert not tracker.is_correction_done("list1", 0, round_num=2)

    tracker.mark_correction_done("list1", 0, round_num=2)
    assert tracker.is_correction_done("list1", 0, round_num=2)


def test_get_correction_rounds_done(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1)
    tracker.mark_correction_done("list1", 0, round_num=2)
    rounds = tracker.get_correction_rounds_done("list1", 0)
    assert rounds == [1, 2]


def test_get_correction_rounds_done_no_corrections(tracker):
    assert tracker.get_correction_rounds_done("list1", 0) == []


def test_correction_separate_segments(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1)
    tracker.mark_correction_done("list1", 1, round_num=1)
    assert tracker.is_correction_done("list1", 0, round_num=1)
    assert tracker.is_correction_done("list1", 1, round_num=1)
    assert not tracker.is_correction_done("list1", 2, round_num=1)


def test_reset_clears_correction(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1)
    tracker.reset()
    assert not tracker.is_correction_done("list1", 0, round_num=1)


def test_summary_includes_correction(tracker):
    tracker.mark_correction_done("list1", 0, round_num=1)
    tracker.mark_correction_done("list1", 1, round_num=1)
    tracker.mark_correction_done("list1", 0, round_num=2)
    tracker.mark_correction_done("list1", 2, round_num=1, error="err")

    summary = tracker.summary()
    assert summary["correction"]["ok"] == 3
    assert summary["correction"]["error"] == 1
    assert summary["correction"]["total"] == 4
    assert set(summary["correction"]["rounds"]) == {1, 2}


def test_total_tokens_includes_correction(tracker):
    tracker.mark_taxonomy_done("list1", "OK", tokens={"input": 100, "output": 50, "cached": 10})
    tracker.mark_correction_done("list1", 0, round_num=1, tokens={"input": 400, "output": 120, "cached": 200})

    tokens = tracker.total_tokens()
    assert tokens["input"] == 500
    assert tokens["output"] == 170
    assert tokens["cached"] == 210
