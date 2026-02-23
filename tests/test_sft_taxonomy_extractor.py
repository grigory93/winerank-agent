"""Tests for taxonomy extractor (LLM calls mocked)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.manifest import ManifestEntry
from winerank.sft.schemas import TaxonomyResult
from winerank.sft.taxonomy_extractor import (
    _parse_taxonomy_response,
    extract_taxonomy_for_all,
    load_taxonomy,
    save_taxonomy,
)


# ---------------------------------------------------------------------------
# _parse_taxonomy_response
# ---------------------------------------------------------------------------


def test_parse_ok_response():
    raw = json.dumps({
        "status": "OK",
        "restaurant_name": "Test Restaurant",
        "categories": [
            {"name": "Champagne", "subcategories": []},
            {
                "name": "Red Wines",
                "subcategories": [
                    {"name": "Burgundy", "subcategories": []}
                ],
            },
        ],
    })
    result = _parse_taxonomy_response(raw, source_file="test.pdf")
    assert result.status == "OK"
    assert result.restaurant_name == "Test Restaurant"
    assert len(result.categories) == 2
    assert result.categories[0].name == "Champagne"
    assert result.categories[1].subcategories[0].name == "Burgundy"


def test_parse_not_a_list_response():
    raw = json.dumps({"status": "NOT_A_LIST"})
    result = _parse_taxonomy_response(raw, source_file="test.pdf")
    assert result.status == "NOT_A_LIST"
    assert result.categories == []


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_taxonomy_response("not json at all", source_file="test.pdf")


# ---------------------------------------------------------------------------
# save_taxonomy / load_taxonomy round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_taxonomy(tmp_path):
    from winerank.sft.schemas import TaxonomyNode
    result = TaxonomyResult(
        status="OK",
        restaurant_name="Quince",
        categories=[TaxonomyNode(name="Champagne", subcategories=[TaxonomyNode(name="Blanc de Blancs")])],
        source_file="test.pdf",
    )
    save_taxonomy(result, tmp_path, "quince")
    loaded = load_taxonomy(tmp_path, "quince")
    assert loaded is not None
    assert loaded.status == "OK"
    assert loaded.restaurant_name == "Quince"
    assert loaded.categories[0].name == "Champagne"
    assert loaded.categories[0].subcategories[0].name == "Blanc de Blancs"


def test_load_taxonomy_not_found(tmp_path):
    result = load_taxonomy(tmp_path, "nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# extract_taxonomy_for_all via SyncExecutor (LLM mocked at litellm level)
# ---------------------------------------------------------------------------


def _make_litellm_response(content: str):
    """Build a mock litellm response object."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage = MagicMock()
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 50
    mock_resp.usage.prompt_tokens_details = None
    return mock_resp


@pytest.fixture
def taxonomy_entry(tmp_path):
    """A ManifestEntry pointing to a temp file with fake text."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF fake content for testing")
    return ManifestEntry(
        list_id="test-list",
        restaurant_name="Test Restaurant",
        file_path=str(pdf),
        file_type="pdf",
    )


@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(
        data_dir=str(tmp_path / "sft"),
        taxonomy_model="gpt-4o-mini",
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


def test_extract_taxonomy_ok(taxonomy_entry, sft_settings, progress):
    ok_response = json.dumps({
        "status": "OK",
        "restaurant_name": "Test Restaurant",
        "categories": [{"name": "Champagne", "subcategories": []}],
    })
    sft_settings.ensure_dirs()

    with patch("winerank.sft.taxonomy_extractor.extract_fulltext") as mock_extract, \
         patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_extract.return_value = "Sample wine list text with lots of wines"
        mock_litellm.completion.return_value = _make_litellm_response(ok_response)

        results = extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress)

    result = results.get("test-list")
    assert result is not None
    assert result.status == "OK"
    assert result.categories[0].name == "Champagne"
    assert progress.get_taxonomy_status("test-list") == "OK"


def test_extract_taxonomy_not_a_list(taxonomy_entry, sft_settings, progress):
    not_a_list_response = json.dumps({"status": "NOT_A_LIST"})
    sft_settings.ensure_dirs()

    with patch("winerank.sft.taxonomy_extractor.extract_fulltext") as mock_extract, \
         patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_extract.return_value = "This is a food menu, not a wine list"
        mock_litellm.completion.return_value = _make_litellm_response(not_a_list_response)

        results = extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress)

    result = results.get("test-list")
    assert result is not None
    assert result.status == "NOT_A_LIST"
    assert progress.get_taxonomy_status("test-list") == "NOT_A_LIST"


def test_extract_taxonomy_uses_full_text(taxonomy_entry, sft_settings, progress):
    sft_settings.ensure_dirs()
    captured_prompts = []

    def fake_completion(**kwargs):
        captured_prompts.append(kwargs["messages"])
        return _make_litellm_response(json.dumps({"status": "OK", "categories": []}))

    with patch("winerank.sft.taxonomy_extractor.extract_fulltext") as mock_extract, \
         patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_extract.return_value = "the full wine list text here"
        mock_litellm.completion.side_effect = fake_completion
        extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress)

    assert len(captured_prompts) == 1
    user_content = captured_prompts[0][1]["content"]
    assert "the full wine list text here" in user_content


def test_extract_taxonomy_uses_correct_model(taxonomy_entry, sft_settings, progress):
    sft_settings.ensure_dirs()

    with patch("winerank.sft.taxonomy_extractor.extract_fulltext") as mock_extract, \
         patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_extract.return_value = "wine list text"
        mock_litellm.completion.return_value = _make_litellm_response(
            json.dumps({"status": "OK", "categories": []})
        )
        extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress)

    call_kwargs = mock_litellm.completion.call_args[1]
    assert call_kwargs["model"] == sft_settings.taxonomy_model


def test_extract_taxonomy_skips_if_done(taxonomy_entry, sft_settings, progress):
    """Should skip if already completed (unless force=True)."""
    sft_settings.ensure_dirs()
    from winerank.sft.schemas import TaxonomyNode
    existing = TaxonomyResult(status="OK", categories=[TaxonomyNode(name="ExistingCat")])
    save_taxonomy(existing, sft_settings.taxonomy_dir, "test-list")
    progress.mark_taxonomy_done("test-list", "OK")

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        results = extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress)

    mock_litellm.completion.assert_not_called()
    assert results.get("test-list") is not None


def test_extract_taxonomy_dry_run(taxonomy_entry, sft_settings, progress):
    sft_settings.ensure_dirs()
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        results = extract_taxonomy_for_all([taxonomy_entry], sft_settings, progress, dry_run=True)

    mock_litellm.completion.assert_not_called()
    assert results.get("test-list") is None


def test_extract_taxonomy_file_not_found(sft_settings, progress):
    sft_settings.ensure_dirs()
    entry = ManifestEntry(
        list_id="missing",
        restaurant_name="Missing",
        file_path="/nonexistent/file.pdf",
        file_type="pdf",
    )
    results = extract_taxonomy_for_all([entry], sft_settings, progress)
    assert results.get("missing") is None
    assert progress.get_taxonomy_status("missing") == "ERROR"
