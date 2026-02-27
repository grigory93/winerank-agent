"""Tests for wine parser (LLM calls mocked)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.schemas import (
    PageParseResult,
    SampleManifestEntry,
    TaxonomyNode,
    TaxonomyResult,
)
from winerank.sft.wine_parser import (
    _is_anthropic_model,
    _parse_wines_from_response,
    load_all_parse_results,
    load_parse_result,
    save_parse_result,
)

SEMANTIC_HTML = """<!doctype html>
<html><body>
<h2>Champagne</h2>
<p>Krug Grande Cuvee NV $450</p>
<p>Dom Perignon 2015 $350</p>
<h2>Red Wines</h2>
<p>Chateau Margaux 2018 $600</p>
</body></html>"""

WINE_JSON_RESPONSE = json.dumps({
    "wines": [
        {
            "name": "Krug Grande Cuvee",
            "winery": "Krug",
            "varietal": "Champagne Blend",
            "wine_type": "Sparkling",
            "country": "France",
            "region": "Champagne",
            "vintage": "NV",
            "price": 450.0,
        },
        {
            "name": "Dom Perignon",
            "winery": "Moet & Chandon",
            "wine_type": "Sparkling",
            "country": "France",
            "vintage": "2015",
            "price": 350.0,
        },
    ]
})


# ---------------------------------------------------------------------------
# _is_anthropic_model
# ---------------------------------------------------------------------------


def test_anthropic_detection_claude():
    assert _is_anthropic_model("claude-opus-4-5") is True
    assert _is_anthropic_model("claude-3-haiku-20240307") is True


def test_anthropic_detection_other():
    assert _is_anthropic_model("gpt-4o") is False
    assert _is_anthropic_model("gemini-flash") is False


# ---------------------------------------------------------------------------
# _parse_wines_from_response
# ---------------------------------------------------------------------------


def test_parse_wines_valid():
    wines = _parse_wines_from_response(WINE_JSON_RESPONSE)
    assert len(wines) == 2
    assert wines[0].name == "Krug Grande Cuvee"
    assert wines[0].wine_type == "Sparkling"
    assert wines[1].price == 350.0


def test_parse_wines_empty():
    wines = _parse_wines_from_response(json.dumps({"wines": []}))
    assert wines == []


def test_parse_wines_invalid_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_wines_from_response("not json")


def test_parse_wines_missing_wines_key():
    # When "wines" key is absent, defaults to empty list (not an error)
    wines = _parse_wines_from_response(json.dumps({"result": []}))
    assert wines == []


def test_parse_wines_wrong_type_raises():
    # When "wines" is not a list, raise ValueError
    with pytest.raises(ValueError):
        _parse_wines_from_response(json.dumps({"wines": "not_a_list"}))


def test_parse_wines_vintage_int_coerced():
    """Teacher model often returns vintage as JSON number; parser accepts and coerces to str."""
    payload = {
        "wines": [
            {"name": "Meursault", "winery": "Antoine Jobard", "vintage": 2023, "price": 395},
            {"name": "Meursault Blagny 1er Cru", "vintage": 2022},
        ]
    }
    wines = _parse_wines_from_response(json.dumps(payload))
    assert len(wines) == 2
    assert wines[0].vintage == "2023"
    assert wines[1].vintage == "2022"


# ---------------------------------------------------------------------------
# parse_all_segments (uses SyncExecutor under the hood -- LLM mocked)
# ---------------------------------------------------------------------------


def _make_litellm_response(content: str, cached: int = 0):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage = MagicMock()
    mock_resp.usage.prompt_tokens = 200
    mock_resp.usage.completion_tokens = 100
    mock_resp.usage.cache_read_input_tokens = cached
    mock_resp.usage.prompt_tokens_details = None
    return mock_resp


@pytest.fixture
def html_sample(tmp_path):
    html_file = tmp_path / "wine_list.html"
    html_file.write_text(SEMANTIC_HTML, encoding="utf-8")
    return SampleManifestEntry(
        list_id="test-list",
        segment_index=0,
        source_file=str(html_file),
        file_type="html",
        char_count=300,
    )


@pytest.fixture
def taxonomy():
    return TaxonomyResult(
        status="OK",
        categories=[TaxonomyNode(name="Champagne"), TaxonomyNode(name="Red Wines")],
    )


@pytest.fixture
def sft_settings(tmp_path):
    from winerank.sft.config import SFTSettings
    return SFTSettings(
        data_dir=str(tmp_path / "sft"),
        teacher_model="claude-opus-4-5",
        training_data_mode="text",
    )


@pytest.fixture
def progress(tmp_path):
    from winerank.sft.progress import ProgressTracker
    return ProgressTracker(tmp_path / "sft" / "progress.json")


def test_parse_all_segments_ok(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()
    sft_settings.taxonomy_dir.mkdir(parents=True, exist_ok=True)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm, \
         patch("winerank.sft.wine_parser.load_taxonomy", return_value=taxonomy):
        mock_litellm.completion.return_value = _make_litellm_response(WINE_JSON_RESPONSE)
        results = parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    assert len(results) == 1
    assert len(results[0].wines) == 2
    assert results[0].wines[0].name == "Krug Grande Cuvee"
    assert results[0].parse_error is None


def test_parse_all_segments_taxonomy_injected(html_sample, taxonomy, sft_settings, progress):
    """Taxonomy text should appear in the user message sent to the model."""
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_completion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_litellm_response(WINE_JSON_RESPONSE)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm, \
         patch("winerank.sft.wine_parser.load_taxonomy", return_value=taxonomy):
        mock_litellm.completion.side_effect = fake_completion
        parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    assert len(captured_messages) == 1
    user_msg = next(m for m in captured_messages[0] if m["role"] == "user")
    user_content_str = str(user_msg["content"])
    assert "Champagne" in user_content_str or "Red Wines" in user_content_str


def test_parse_all_segments_system_prompt_has_schema(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()
    captured_messages = []

    def fake_completion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_litellm_response(WINE_JSON_RESPONSE)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm, \
         patch("winerank.sft.wine_parser.load_taxonomy", return_value=taxonomy):
        mock_litellm.completion.side_effect = fake_completion
        parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    system_msg = next(m for m in captured_messages[0] if m["role"] == "system")
    assert "varietal" in system_msg["content"]
    assert "appellation" in system_msg["content"]


def test_parse_all_segments_uses_correct_model(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm, \
         patch("winerank.sft.wine_parser.load_taxonomy", return_value=taxonomy):
        mock_litellm.completion.return_value = _make_litellm_response(WINE_JSON_RESPONSE)
        parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    call_kwargs = mock_litellm.completion.call_args[1]
    assert call_kwargs["model"] == sft_settings.teacher_model


def test_parse_all_segments_cache_points_for_anthropic(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm, \
         patch("winerank.sft.wine_parser.load_taxonomy", return_value=taxonomy):
        mock_litellm.completion.return_value = _make_litellm_response(WINE_JSON_RESPONSE, cached=800)
        results = parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    # Cache control injection points should cause litellm to receive the kwarg
    call_kwargs = mock_litellm.completion.call_args[1]
    assert "cache_control_injection_points" in call_kwargs
    # Cached tokens should be captured
    assert results[0].cached_tokens == 800


def test_parse_all_segments_skips_if_done(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()
    # Pre-create a result and mark as done
    existing = PageParseResult(
        segment_id="test-list__0",
        list_id="test-list",
        segment_index=0,
        source_file=str(html_sample.source_file),
        segment_text="existing text",
        taxonomy_text="existing taxonomy",
        wines=[],
    )
    save_parse_result(existing, sft_settings.parsed_dir)
    progress.mark_parse_done("test-list", 0)

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        parse_all_segments([html_sample], settings=sft_settings, progress=progress)

    mock_litellm.completion.assert_not_called()


def test_parse_all_segments_dry_run(html_sample, taxonomy, sft_settings, progress):
    from winerank.sft.wine_parser import parse_all_segments

    sft_settings.ensure_dirs()
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        results = parse_all_segments([html_sample], settings=sft_settings, progress=progress, dry_run=True)

    mock_litellm.completion.assert_not_called()
    assert results == []


# ---------------------------------------------------------------------------
# save_parse_result / load_parse_result round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_parse_result(tmp_path):
    from winerank.sft.schemas import WineEntry
    result = PageParseResult(
        segment_id="list1__5",
        list_id="list1",
        segment_index=5,
        source_file="test.pdf",
        segment_text="Krug Grande Cuvee NV $450",
        taxonomy_text="Champagne",
        wines=[WineEntry(name="Krug Grande Cuvee", price=450.0)],
        input_tokens=200,
        output_tokens=100,
    )
    save_parse_result(result, tmp_path)
    loaded = load_parse_result(tmp_path, "list1", 5)
    assert loaded is not None
    assert loaded.segment_id == "list1__5"
    assert len(loaded.wines) == 1
    assert loaded.wines[0].name == "Krug Grande Cuvee"


def test_load_parse_result_not_found(tmp_path):
    result = load_parse_result(tmp_path, "nonexistent", 0)
    assert result is None


def test_load_all_parse_results(tmp_path):
    from winerank.sft.schemas import WineEntry
    for i in range(3):
        r = PageParseResult(
            segment_id=f"list1__{i}",
            list_id="list1",
            segment_index=i,
            source_file="test.pdf",
            segment_text=f"text {i}",
            taxonomy_text="Champagne",
            wines=[WineEntry(name=f"Wine {i}")],
        )
        save_parse_result(r, tmp_path)

    all_results = load_all_parse_results(tmp_path)
    assert len(all_results) == 3
