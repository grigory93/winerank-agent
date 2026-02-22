"""
Page reader: extract text and images from PDF and HTML wine list files.

Provides:
  - Full-text extraction (reuses WineListTextExtractor)
  - Per-page text extraction for PDFs
  - PDF page-to-image conversion (vision mode)
  - HTML segmentation: heading-based or ALL-CAPS text pattern fallback
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Optional

import pdfplumber
from bs4 import BeautifulSoup

from winerank.sft.schemas import WineSegment


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------


def extract_pdf_pages(
    file_path: Path,
    list_id: str,
    min_chars: int = 50,
) -> list[WineSegment]:
    """
    Extract each page of a PDF as a separate WineSegment.

    Args:
        file_path: Path to PDF file.
        list_id: Identifier for the wine list.
        min_chars: Minimum character count to include a page.

    Returns:
        List of WineSegment objects, one per non-blank page.
    """
    segments: list[WineSegment] = []
    with pdfplumber.open(file_path) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text(layout=True) or ""
            if len(text.strip()) < min_chars:
                continue
            segments.append(
                WineSegment(
                    list_id=list_id,
                    segment_index=idx,
                    segment_text=text,
                    source_file=str(file_path),
                    file_type="pdf",
                )
            )
    return segments


def extract_pdf_fulltext(file_path: Path) -> str:
    """
    Extract full text of a PDF (all pages concatenated).

    Args:
        file_path: Path to PDF file.

    Returns:
        Concatenated text of all pages.
    """
    parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts)


def render_pdf_page_to_base64(file_path: Path, page_index: int) -> Optional[str]:
    """
    Render a single PDF page as a PNG image and return as base64-encoded string.

    Requires the `pdf2image` package (poppler must be installed).

    Args:
        file_path: Path to PDF file.
        page_index: Zero-based page index.

    Returns:
        Base64-encoded PNG string, or None if rendering fails.
    """
    try:
        from pdf2image import convert_from_path  # type: ignore[import-untyped]

        images = convert_from_path(
            str(file_path),
            first_page=page_index + 1,
            last_page=page_index + 1,
            dpi=150,
        )
        if not images:
            return None
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        raise ImportError(
            "pdf2image is required for vision mode. "
            "Install with: pip install pdf2image"
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML segmentation helpers
# ---------------------------------------------------------------------------

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# Match lines that are ALL CAPS (at least 3 chars, no lowercase), possibly
# surrounded by whitespace -- typical section headers in SPA-rendered wine lists
_ALL_CAPS_PATTERN = re.compile(r"^[A-Z][A-Z\s\-&'/,\.0-9]{2,}$")


def _segment_html_by_headings(
    soup: BeautifulSoup,
    list_id: str,
    source_file: str,
    min_chars: int = 50,
) -> list[WineSegment]:
    """Segment HTML by <h1>-<h6> heading tags."""
    segments: list[WineSegment] = []
    current_lines: list[str] = []
    segment_idx = 0

    def flush(idx: int) -> None:
        text = "\n".join(current_lines).strip()
        if len(text) >= min_chars:
            segments.append(
                WineSegment(
                    list_id=list_id,
                    segment_index=idx,
                    segment_text=text,
                    source_file=source_file,
                    file_type="html",
                )
            )

    # Walk all elements in document order
    for element in soup.find_all(True):
        if element.name in _HEADING_TAGS:
            # When we hit a heading, flush the current accumulation
            if current_lines:
                flush(segment_idx)
                segment_idx += 1
                current_lines = []
            heading_text = element.get_text(separator=" ", strip=True)
            if heading_text:
                current_lines.append(heading_text)
        elif element.name in ("p", "li", "td", "span", "div"):
            # Only harvest leaf-ish text nodes (NavigableString has .name=None, Tag has .name=str)
            from bs4 import Tag as _Tag
            child_tags = [c for c in element.children if isinstance(c, _Tag)]
            if child_tags:
                continue  # non-leaf, will be visited individually
            text = element.get_text(separator=" ", strip=True)
            if text:
                current_lines.append(text)

    if current_lines:
        flush(segment_idx)

    return segments


def _segment_html_by_caps_patterns(
    html_text: str,
    list_id: str,
    source_file: str,
    min_chars: int = 50,
) -> list[WineSegment]:
    """
    Fallback segmenter for flat SPA-rendered HTML.

    Splits on lines that are ALL CAPS (typical section headers in div-based
    wine lists like Fiola / Per Se Binwise pages).
    """
    segments: list[WineSegment] = []
    current_lines: list[str] = []
    segment_idx = 0

    def flush(idx: int) -> None:
        text = "\n".join(current_lines).strip()
        if len(text) >= min_chars:
            segments.append(
                WineSegment(
                    list_id=list_id,
                    segment_index=idx,
                    segment_text=text,
                    source_file=source_file,
                    file_type="html",
                )
            )

    for line in html_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _ALL_CAPS_PATTERN.match(stripped):
            if current_lines:
                flush(segment_idx)
                segment_idx += 1
                current_lines = []
        current_lines.append(stripped)

    if current_lines:
        flush(segment_idx)

    return segments


def extract_html_segments(
    file_path: Path,
    list_id: str,
    min_chars: int = 50,
) -> list[WineSegment]:
    """
    Segment an HTML wine list into sections.

    Strategy:
    1. Try heading-based segmentation (h1-h6) -- works for traditional HTML.
    2. If that produces < 2 meaningful segments, fall back to ALL-CAPS pattern
       splitting on the extracted plain text -- works for SPA-rendered pages.

    Args:
        file_path: Path to HTML file.
        list_id: Identifier for the wine list.
        min_chars: Minimum characters to keep a segment.

    Returns:
        List of WineSegment objects.
    """
    raw_html = file_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove noise tags
    for tag in soup(["script", "style", "noscript", "svg", "meta", "link"]):
        tag.decompose()

    segments = _segment_html_by_headings(
        soup, list_id=list_id, source_file=str(file_path), min_chars=min_chars
    )

    if len(segments) >= 2:
        return segments

    # Fallback: extract all text and split by ALL-CAPS headers
    from winerank.crawler.text_extractor import WineListTextExtractor

    extractor = WineListTextExtractor()
    plain_text = extractor.extract_from_file(str(file_path))
    return _segment_html_by_caps_patterns(
        plain_text, list_id=list_id, source_file=str(file_path), min_chars=min_chars
    )


def extract_html_fulltext(file_path: Path) -> str:
    """
    Extract full text from an HTML file using WineListTextExtractor.

    Args:
        file_path: Path to HTML file.

    Returns:
        Extracted text string.
    """
    from winerank.crawler.text_extractor import WineListTextExtractor

    extractor = WineListTextExtractor()
    return extractor.extract_from_file(str(file_path))


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------


def extract_fulltext(file_path: Path) -> str:
    """
    Extract the complete text of a PDF or HTML wine list.

    Args:
        file_path: Path to PDF or HTML file.

    Returns:
        Extracted text.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file type is unsupported.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_fulltext(file_path)
    elif suffix in (".html", ".htm"):
        return extract_html_fulltext(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")


def extract_segments(
    file_path: Path,
    list_id: str,
    min_chars: int = 50,
) -> list[WineSegment]:
    """
    Extract all segments from a PDF or HTML wine list.

    Args:
        file_path: Path to PDF or HTML file.
        list_id: Identifier for the wine list.
        min_chars: Minimum characters to keep a segment.

    Returns:
        List of WineSegment objects.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file type is unsupported.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_pages(file_path, list_id=list_id, min_chars=min_chars)
    elif suffix in (".html", ".htm"):
        return extract_html_segments(file_path, list_id=list_id, min_chars=min_chars)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")
