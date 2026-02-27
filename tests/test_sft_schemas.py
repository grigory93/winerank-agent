"""Tests for SFT Pydantic schemas."""
import pytest
from pydantic import ValidationError

from winerank.sft.schemas import (
    DatasetMetadata,
    JudgeIssue,
    JudgeResult,
    ManifestEntry,
    PageParseResult,
    SampleManifestEntry,
    TaxonomyNode,
    TaxonomyResult,
    TrainingSample,
    WineEntry,
)


# ---------------------------------------------------------------------------
# TaxonomyNode
# ---------------------------------------------------------------------------


def test_taxonomy_node_basic():
    node = TaxonomyNode(name="Champagne")
    assert node.name == "Champagne"
    assert node.subcategories == []


def test_taxonomy_node_nested():
    node = TaxonomyNode(
        name="France",
        subcategories=[
            TaxonomyNode(name="Burgundy", subcategories=[TaxonomyNode(name="Cote de Nuits")])
        ],
    )
    assert node.subcategories[0].name == "Burgundy"
    assert node.subcategories[0].subcategories[0].name == "Cote de Nuits"


def test_taxonomy_node_flat_list():
    node = TaxonomyNode(
        name="France",
        subcategories=[
            TaxonomyNode(name="Burgundy", subcategories=[TaxonomyNode(name="Cote de Nuits")])
        ],
    )
    flat = node.flat_list()
    assert "France" in flat
    assert "France > Burgundy" in flat
    assert "France > Burgundy > Cote de Nuits" in flat


def test_taxonomy_node_to_text():
    node = TaxonomyNode(name="Champagne", subcategories=[TaxonomyNode(name="Blanc de Blancs")])
    text = node.to_text()
    assert "Champagne" in text
    assert "Blanc de Blancs" in text


def test_taxonomy_node_serialization():
    node = TaxonomyNode(name="Bordeaux")
    d = node.model_dump()
    assert d["name"] == "Bordeaux"
    assert d["subcategories"] == []


# ---------------------------------------------------------------------------
# TaxonomyResult
# ---------------------------------------------------------------------------


def test_taxonomy_result_ok():
    result = TaxonomyResult(
        status="OK",
        restaurant_name="Test",
        categories=[TaxonomyNode(name="Champagne")],
    )
    assert result.status == "OK"
    assert len(result.categories) == 1


def test_taxonomy_result_not_a_list():
    result = TaxonomyResult(status="NOT_A_LIST")
    assert result.status == "NOT_A_LIST"
    assert result.categories == []


def test_taxonomy_result_flat_categories():
    result = TaxonomyResult(
        status="OK",
        categories=[
            TaxonomyNode(name="Red Wines", subcategories=[TaxonomyNode(name="Burgundy")]),
            TaxonomyNode(name="White Wines"),
        ],
    )
    flat = result.flat_categories()
    assert "Red Wines" in flat
    assert "Red Wines > Burgundy" in flat
    assert "White Wines" in flat


def test_taxonomy_result_to_prompt_text_empty():
    result = TaxonomyResult(status="OK", categories=[])
    text = result.to_prompt_text()
    assert "no taxonomy" in text.lower()


def test_taxonomy_result_to_prompt_text_with_categories():
    result = TaxonomyResult(
        status="OK",
        categories=[TaxonomyNode(name="Champagne")],
    )
    text = result.to_prompt_text()
    assert "Champagne" in text


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------


def test_judge_result_valid():
    jr = JudgeResult(
        segment_id="list1__0",
        list_id="list1",
        segment_index=0,
        score=0.9,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
    )
    assert jr.score == 0.9
    assert jr.recommendation == "accept"


def test_judge_result_score_clamped_high():
    jr = JudgeResult(
        segment_id="x__0",
        list_id="x",
        segment_index=0,
        score=1.5,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
    )
    assert jr.score == 1.0


def test_judge_result_score_clamped_low():
    jr = JudgeResult(
        segment_id="x__0",
        list_id="x",
        segment_index=0,
        score=-0.5,
        wine_count_match=False,
        issues=[JudgeIssue(type="other", description="test")],
        recommendation="reject",
    )
    assert jr.score == 0.0


def test_judge_result_invalid_recommendation():
    with pytest.raises(ValidationError):
        JudgeResult(
            segment_id="x__0",
            list_id="x",
            segment_index=0,
            score=0.5,
            wine_count_match=False,
            issues=[],
            recommendation="maybe",  # pyright: ignore[reportArgumentType]
        )


def test_judge_result_needs_reparse_default():
    r = JudgeResult(
        segment_id="x__0",
        list_id="x",
        segment_index=0,
        score=0.9,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
    )
    assert r.needs_reparse is False
    assert r.correction_round == 0


def test_judge_result_correction_round():
    r = JudgeResult(
        segment_id="x__0",
        list_id="x",
        segment_index=0,
        score=0.9,
        wine_count_match=True,
        issues=[],
        recommendation="accept",
        correction_round=2,
    )
    assert r.correction_round == 2


# ---------------------------------------------------------------------------
# JudgeIssue
# ---------------------------------------------------------------------------


def test_judge_issue_all_types():
    for itype in ("missing_wine", "hallucinated_wine", "wrong_attribute", "wrong_price", "other"):
        issue = JudgeIssue(type=itype, description=f"test {itype}")
        assert issue.type == itype


def test_judge_issue_invalid_type():
    with pytest.raises(ValidationError):
        JudgeIssue(type="unknown_type", description="test")  # pyright: ignore[reportArgumentType]


def test_judge_issue_optional_fields():
    issue = JudgeIssue(type="wrong_attribute", description="Missing appellation",
                       wine_name="Opus One", field="appellation",
                       current_value=None, expected_value="Napa Valley")
    assert issue.wine_name == "Opus One"
    assert issue.current_value is None
    assert issue.expected_value == "Napa Valley"


def test_judge_result_structured_issues():
    r = JudgeResult(
        segment_id="x__0",
        list_id="x",
        segment_index=0,
        score=0.6,
        wine_count_match=False,
        issues=[
            JudgeIssue(type="missing_wine", description="Dom Perignon not found", wine_name="Dom Perignon"),
            JudgeIssue(type="wrong_price", description="Price wrong", field="price",
                      current_value="850", expected_value="85"),
        ],
        recommendation="review",
        needs_reparse=True,
    )
    assert r.issues[0].type == "missing_wine"
    assert r.issues[0].wine_name == "Dom Perignon"
    assert r.issues[1].type == "wrong_price"
    assert r.needs_reparse is True


# ---------------------------------------------------------------------------
# WineEntry
# ---------------------------------------------------------------------------


def test_wine_entry_required_name():
    w = WineEntry(name="Dom Perignon")
    assert w.name == "Dom Perignon"
    assert w.price is None


def test_wine_entry_full():
    w = WineEntry(
        name="Krug Grande Cuvee",
        winery="Krug",
        varietal="Champagne Blend",
        wine_type="Sparkling",
        country="France",
        region="Champagne",
        price=450.0,
        vintage="NV",
    )
    assert w.wine_type == "Sparkling"
    assert w.price == 450.0


def test_wine_entry_missing_name_raises():
    with pytest.raises(ValidationError):
        WineEntry()  # pyright: ignore[reportCallIssue]


# ---------------------------------------------------------------------------
# PageParseResult
# ---------------------------------------------------------------------------


def test_page_parse_result_basic():
    pr = PageParseResult(
        segment_id="list1__3",
        list_id="list1",
        segment_index=3,
        source_file="test.pdf",
        segment_text="Some wines here",
        taxonomy_text="Champagne\nRed Wines",
        wines=[WineEntry(name="Dom Perignon")],
    )
    assert pr.segment_id == "list1__3"
    assert len(pr.wines) == 1
    assert pr.correction_round == 0  # default


def test_page_parse_result_correction_round():
    pr = PageParseResult(
        segment_id="list1__3",
        list_id="list1",
        segment_index=3,
        source_file="test.pdf",
        segment_text="Some wines here",
        taxonomy_text="Champagne\nRed Wines",
        wines=[WineEntry(name="Dom Perignon")],
        correction_round=2,
    )
    assert pr.correction_round == 2


# ---------------------------------------------------------------------------
# ManifestEntry & SampleManifestEntry
# ---------------------------------------------------------------------------


def test_manifest_entry():
    e = ManifestEntry(
        list_id="test-list",
        restaurant_name="Test Restaurant",
        file_path="data/examples/test.pdf",
        file_type="pdf",
    )
    assert e.list_id == "test-list"
    assert e.file_type == "pdf"


def test_sample_manifest_entry():
    s = SampleManifestEntry(
        list_id="test",
        segment_index=5,
        source_file="test.pdf",
        file_type="pdf",
        char_count=500,
    )
    assert s.segment_index == 5


# ---------------------------------------------------------------------------
# TrainingSample & DatasetMetadata
# ---------------------------------------------------------------------------


def test_training_sample():
    ts = TrainingSample(
        messages=[
            {"role": "system", "content": "You are an extractor"},
            {"role": "user", "content": "Parse this"},
            {"role": "assistant", "content": '{"wines": []}'},
        ]
    )
    assert len(ts.messages) == 3
    assert ts.messages[0]["role"] == "system"


def test_dataset_metadata():
    meta = DatasetMetadata(
        generated_at="2026-01-01T00:00:00Z",
        taxonomy_model="gpt-4o-mini",
        teacher_model="claude-opus-4-5",
        training_data_mode="text",
        num_samples_target=500,
        num_samples_actual=450,
        num_lists_used=38,
        not_a_list_count=3,
        judge_filtered_count=10,
        seed=42,
        min_judge_score=0.0,
    )
    assert meta.num_samples_actual == 450
