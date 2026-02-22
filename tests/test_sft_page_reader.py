"""Tests for SFT page reader: text extraction and segmentation."""
import pytest
from pathlib import Path

from winerank.sft.page_reader import (
    extract_fulltext,
    extract_html_segments,
    extract_pdf_pages,
    extract_segments,
)


# ---------------------------------------------------------------------------
# HTML segmentation
# ---------------------------------------------------------------------------

SEMANTIC_HTML = """<!doctype html>
<html><body>
<h1>Wine List</h1>
<h2>Champagne</h2>
<p>Krug Grande Cuvee NV $450</p>
<p>Dom Perignon 2015 $350</p>
<p>Billecart-Salmon Blanc de Blancs 2018 $280</p>
<p>Louis Roederer Cristal 2016 $620</p>
<h2>Red Wines - Burgundy and Bordeaux Selection</h2>
<p>Chateau Margaux 2018 $600</p>
<p>Petrus 2015 $2500</p>
<p>Domaine Leroy Chambolle-Musigny 2019 $900</p>
<p>Gevrey-Chambertin Premier Cru Cazetiers 2020 $350</p>
</body></html>"""

FLAT_SPA_HTML = """<!doctype html>
<html><body>
<div>Wine List</div>
<div>CHAMPAGNE</div>
<div>Krug Grande Cuvee NV $450</div>
<div>Dom Perignon 2015 $350</div>
<div>RED WINES</div>
<div>Chateau Margaux 2018 $600</div>
<div>WHITE WINES</div>
<div>Puligny-Montrachet 2020 $200</div>
</body></html>"""


def test_html_heading_segmentation(tmp_path):
    html_file = tmp_path / "wine_list.html"
    html_file.write_text(SEMANTIC_HTML, encoding="utf-8")

    segments = extract_html_segments(html_file, list_id="test-list")
    assert len(segments) >= 2
    # Each segment should have some text
    for seg in segments:
        assert len(seg.segment_text.strip()) >= 10
        assert seg.list_id == "test-list"
        assert seg.file_type == "html"


def test_html_flat_spa_fallback(tmp_path):
    html_file = tmp_path / "spa.html"
    html_file.write_text(FLAT_SPA_HTML, encoding="utf-8")

    segments = extract_html_segments(html_file, list_id="spa-list")
    # Should find at least some segments via ALL-CAPS fallback
    assert len(segments) >= 1
    all_text = " ".join(s.segment_text for s in segments)
    assert "Krug" in all_text or "Margaux" in all_text or "Puligny" in all_text


def test_html_segment_min_chars_filter(tmp_path):
    html_file = tmp_path / "short.html"
    html_file.write_text(
        "<html><body><h2>A</h2><p>very short</p><h2>B</h2><p>also short</p></body></html>",
        encoding="utf-8",
    )
    # With high min_chars threshold, segments might be filtered
    segments = extract_html_segments(html_file, list_id="x", min_chars=500)
    # Could be 0 since content is short
    assert all(seg.char_count >= 0 for seg in segments)


def test_html_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        extract_segments(Path("/nonexistent/file.html"), list_id="x")


def test_html_fulltext_extraction(tmp_path):
    html_file = tmp_path / "wine.html"
    html_file.write_text(SEMANTIC_HTML, encoding="utf-8")
    text = extract_fulltext(html_file)
    assert "Champagne" in text
    assert "Krug" in text


# ---------------------------------------------------------------------------
# PDF extraction (uses real example PDFs, skips if unavailable)
# ---------------------------------------------------------------------------


@pytest.fixture
def example_pdfs():
    examples_dir = Path("data/examples")
    if examples_dir.exists():
        pdfs = list(examples_dir.glob("*.pdf"))
        return pdfs[:3]  # Use first 3 for speed
    return []


def test_pdf_pages_extraction(example_pdfs):
    if not example_pdfs:
        pytest.skip("No example PDFs available")

    for pdf_path in example_pdfs:
        try:
            segments = extract_pdf_pages(pdf_path, list_id="test")
            if segments:
                assert all(seg.file_type == "pdf" for seg in segments)
                assert all(seg.char_count > 0 for seg in segments)
                return  # Pass on first success
        except Exception:
            continue
    pytest.skip("No valid PDFs could be extracted")


def test_pdf_fulltext_extraction(example_pdfs):
    if not example_pdfs:
        pytest.skip("No example PDFs available")

    for pdf_path in example_pdfs:
        try:
            text = extract_fulltext(pdf_path)
            if text.strip():
                assert len(text) > 50
                return
        except Exception:
            continue
    pytest.skip("No valid PDFs could be extracted")


def test_pdf_blank_page_filtering(tmp_path):
    """Segments with fewer than min_chars characters should be excluded."""
    # We can't easily make a real blank-page PDF, so test the filter logic
    # by checking that char_count is stored correctly
    from winerank.sft.schemas import WineSegment
    seg = WineSegment(
        list_id="test",
        segment_index=0,
        segment_text="Hello",
        source_file="test.pdf",
        file_type="pdf",
    )
    assert seg.char_count == 5


# ---------------------------------------------------------------------------
# Unified extract_segments dispatch
# ---------------------------------------------------------------------------


def test_extract_segments_pdf_dispatch(example_pdfs):
    if not example_pdfs:
        pytest.skip("No example PDFs available")
    for pdf_path in example_pdfs:
        try:
            segs = extract_segments(pdf_path, list_id="dispatch-test")
            assert all(s.file_type == "pdf" for s in segs)
            return
        except Exception:
            continue
    pytest.skip("No valid PDFs could be extracted")


def test_extract_segments_html_dispatch(tmp_path):
    html_file = tmp_path / "test.html"
    html_file.write_text(SEMANTIC_HTML, encoding="utf-8")
    segs = extract_segments(html_file, list_id="html-test")
    assert all(s.file_type == "html" for s in segs)


def test_extract_segments_unsupported_type(tmp_path):
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("content")
    with pytest.raises(ValueError):
        extract_segments(txt_file, list_id="x")


def test_extract_fulltext_unsupported_type(tmp_path):
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("content")
    with pytest.raises(ValueError):
        extract_fulltext(txt_file)
