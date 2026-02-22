"""Tests for SFT configuration."""
import pytest


def test_default_values():
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.taxonomy_model == "gpt-4o-mini"
    assert s.teacher_model == "claude-opus-4-5"
    assert s.judge_model == "claude-opus-4-5"
    assert s.training_data_mode == "text"
    assert s.num_samples == 500
    assert s.seed == 42
    assert s.min_segment_chars == 50
    assert s.min_judge_score == 0.0


def test_override_taxonomy_model(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_TAXONOMY_MODEL", "gemini-flash")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.taxonomy_model == "gemini-flash"


def test_override_teacher_model(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_TEACHER_MODEL", "gpt-4o")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.teacher_model == "gpt-4o"


def test_override_judge_model(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_JUDGE_MODEL", "gpt-4o")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.judge_model == "gpt-4o"


def test_override_mode_vision(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_TRAINING_DATA_MODE", "vision")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.training_data_mode == "vision"


def test_override_mode_text(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_TRAINING_DATA_MODE", "text")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.training_data_mode == "text"


def test_invalid_mode_raises():
    from winerank.sft.config import SFTSettings
    with pytest.raises(Exception):
        SFTSettings(training_data_mode="invalid")


def test_override_num_samples(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_NUM_SAMPLES", "200")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.num_samples == 200


def test_override_seed(monkeypatch):
    monkeypatch.setenv("WINERANK_SFT_SEED", "99")
    from winerank.sft.config import SFTSettings
    s = SFTSettings()
    assert s.seed == 99


def test_path_properties(tmp_path):
    from winerank.sft.config import SFTSettings
    s = SFTSettings(data_dir=str(tmp_path / "sft"))
    assert s.data_path == tmp_path / "sft"
    assert s.taxonomy_dir == tmp_path / "sft" / "taxonomy"
    assert s.parsed_dir == tmp_path / "sft" / "parsed"
    assert s.judged_dir == tmp_path / "sft" / "judged"
    assert s.dataset_dir == tmp_path / "sft" / "dataset"


def test_ensure_dirs(tmp_path):
    from winerank.sft.config import SFTSettings
    s = SFTSettings(data_dir=str(tmp_path / "sft"))
    s.ensure_dirs()
    assert s.taxonomy_dir.exists()
    assert s.parsed_dir.exists()
    assert s.judged_dir.exists()
    assert s.dataset_dir.exists()
