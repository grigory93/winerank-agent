"""SFT Training Data Review page for DB Manager.

Four-panel layout:
  1. Original segment (rendered PDF page or HTML text)
  2. Taxonomy (hierarchical wine categories)
  3. Parsed wines (JSON / table view) with correction round badge
  4. Judge review results (structured issues, score, recommendation)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

import streamlit as st

# ---------------------------------------------------------------------------
# Data loading helpers (lazy imports to avoid hard deps at import time)
# ---------------------------------------------------------------------------


def _get_sft_data_paths():
    from winerank.sft.config import get_sft_settings
    return get_sft_settings()


@st.cache_data(ttl=30)
def _load_manifest():
    settings = _get_sft_data_paths()
    if not settings.manifest_file.exists():
        return None
    from winerank.sft.manifest import load_manifest
    return load_manifest(settings.manifest_file)


@st.cache_data(ttl=30)
def _load_taxonomy(list_id: str):
    settings = _get_sft_data_paths()
    from winerank.sft.taxonomy_extractor import load_taxonomy
    return load_taxonomy(settings.taxonomy_dir, list_id)


@st.cache_data(ttl=30)
def _load_parse_result(list_id: str, segment_index: int):
    settings = _get_sft_data_paths()
    from winerank.sft.wine_parser import load_parse_result
    return load_parse_result(settings.parsed_dir, list_id, segment_index)


@st.cache_data(ttl=30)
def _load_judge_result(list_id: str, segment_index: int):
    settings = _get_sft_data_paths()
    from winerank.sft.judge_reviewer import load_judge_result
    return load_judge_result(settings.judged_dir, list_id, segment_index)


@st.cache_data(ttl=30)
def _load_all_judge_results() -> dict:
    settings = _get_sft_data_paths()
    from winerank.sft.judge_reviewer import load_all_judge_results
    return {k: v.model_dump() for k, v in load_all_judge_results(settings.judged_dir).items()}


@st.cache_data(ttl=30)
def _load_samples():
    settings = _get_sft_data_paths()
    if not settings.samples_file.exists():
        return []
    from winerank.sft.page_sampler import load_samples
    return load_samples(settings.samples_file)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _render_score_badge(score: float) -> str:
    if score >= 0.8:
        color = "green"
        emoji = "✅"
    elif score >= 0.5:
        color = "orange"
        emoji = "⚠️"
    else:
        color = "red"
        emoji = "❌"
    return f'<span style="color:{color};font-weight:bold">{emoji} {score:.2f}</span>'


def _render_recommendation_pill(rec: str) -> str:
    colors = {"accept": "#28a745", "review": "#ffc107", "reject": "#dc3545"}
    color = colors.get(rec, "#6c757d")
    return f'<span style="background:{color};color:white;padding:3px 10px;border-radius:12px;font-size:0.85em">{rec.upper()}</span>'


def _render_correction_badge(correction_round: int) -> str:
    if correction_round == 0:
        return '<span style="background:#6c757d;color:white;padding:2px 8px;border-radius:8px;font-size:0.8em">ORIGINAL</span>'
    colors = ["#17a2b8", "#6f42c1", "#fd7e14"]
    color = colors[min(correction_round - 1, len(colors) - 1)]
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:8px;font-size:0.8em">CORRECTED R{correction_round}</span>'


def _render_issue_card(issue: dict) -> None:
    """Render a single structured JudgeIssue as a colored card."""
    itype = issue.get("type", "other")
    desc = issue.get("description", "")
    wine_name = issue.get("wine_name")
    field = issue.get("field")
    current = issue.get("current_value")
    expected = issue.get("expected_value")

    # Color by issue type
    type_styles = {
        "missing_wine": ("🍷", "#dc3545"),
        "hallucinated_wine": ("👻", "#fd7e14"),
        "wrong_attribute": ("🔧", "#ffc107"),
        "wrong_price": ("💰", "#e83e8c"),
        "other": ("ℹ️", "#6c757d"),
    }
    icon, color = type_styles.get(itype, ("ℹ️", "#6c757d"))

    label = itype.replace("_", " ").upper()
    header = f'{icon} <span style="color:{color};font-weight:bold">{label}</span>'
    if wine_name:
        header += f' — <em>{wine_name}</em>'

    detail_parts = [desc]
    if field and (current or expected):
        detail_parts.append(f"`{field}`: `{current}` → `{expected}`")

    with st.container():
        st.markdown(header, unsafe_allow_html=True)
        for part in detail_parts:
            st.caption(part)


def _render_pdf_page_image(source_file: str, segment_index: int) -> bool:
    """Render a PDF page as an image. Returns True if successful."""
    try:
        from winerank.sft.page_reader import render_pdf_page_to_base64
        b64 = render_pdf_page_to_base64(Path(source_file), segment_index)
        if b64:
            img_bytes = base64.b64decode(b64)
            st.image(img_bytes, width='stretch', caption=f"Page {segment_index + 1}")
            return True
    except ImportError:
        pass
    return False


def _render_html_segment(html_file: str, segment_index: int) -> None:
    """Render an HTML segment section."""
    try:
        from winerank.sft.page_reader import extract_html_segments
        segs = extract_html_segments(Path(html_file), list_id="preview", min_chars=0)
        for seg in segs:
            if seg.segment_index == segment_index:
                st.text_area("HTML Segment Text", seg.segment_text, height=300)
                return
    except Exception as e:
        st.warning(f"Could not load HTML segment: {e}")


def _render_taxonomy_tree(taxonomy) -> None:
    """Render taxonomy as an indented tree in Streamlit."""
    if taxonomy is None:
        st.info("No taxonomy available for this wine list.")
        return
    if taxonomy.status == "NOT_A_LIST":
        st.warning("This file was classified as NOT_A_LIST during taxonomy extraction.")
        return
    if not taxonomy.categories:
        st.info("Taxonomy extracted but no categories found.")
        return

    def render_node(node, depth=0):
        indent = "  " * depth
        st.markdown(f"{indent}**{node.name}**")
        for sub in node.subcategories:
            render_node(sub, depth + 1)

    for cat in taxonomy.categories:
        render_node(cat)


def _render_wines_table(parse_result) -> None:
    """Render parsed wines as a Streamlit table."""
    import pandas as pd

    if not parse_result:
        st.info("No parse result found for this segment.")
        return
    if parse_result.parse_error:
        st.error(f"Parse error: {parse_result.parse_error}")
        return
    if not parse_result.wines:
        st.warning("No wines were extracted from this segment.")
        return

    rows = []
    for w in parse_result.wines:
        rows.append({
            "Name": w.name,
            "Winery": w.winery or "",
            "Varietal": w.varietal or "",
            "Type": w.wine_type or "",
            "Country": w.country or "",
            "Region": w.region or "",
            "Appellation": w.appellation or "",
            "Vintage": w.vintage or "",
            "Price": w.price or "",
            "Note": (w.note or "")[:60],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)
    st.caption(f"{len(parse_result.wines)} wine{'s' if len(parse_result.wines) != 1 else ''} extracted")


# ---------------------------------------------------------------------------
# Main page renderer
# ---------------------------------------------------------------------------


def render():
    """Render the SFT Training Data Review page."""
    st.title("SFT Training Data Review")

    settings = _get_sft_data_paths()

    # Check pipeline state
    if not settings.manifest_file.exists():
        st.warning("No manifest found. Run `winerank sft-data init` to get started.")
        return

    manifest = _load_manifest()
    if not manifest or not manifest.lists:
        st.warning("Manifest is empty.")
        return

    samples = _load_samples()
    all_judge_results = _load_all_judge_results()
    has_judge = bool(all_judge_results)

    # ---------------------------------------------------------------------------
    # Sidebar: filters and navigation
    # ---------------------------------------------------------------------------
    st.sidebar.header("Filters & Navigation")

    # List selector
    list_names = {e.list_id: e.restaurant_name for e in manifest.lists}

    # Filter by judge recommendation (if judge results available)
    if has_judge:
        rec_filter = st.sidebar.selectbox(
            "Filter by Judge Recommendation",
            ["All", "accept", "review", "reject"],
            index=0,
        )
        min_score = st.sidebar.slider("Min Judge Score", 0.0, 1.0, 0.0, 0.05)
        # Filter by correction status
        correction_filter = st.sidebar.selectbox(
            "Filter by Correction Status",
            ["All", "Original only", "Corrected only"],
            index=0,
        )
    else:
        rec_filter = "All"
        min_score = 0.0
        correction_filter = "All"

    # Build list of available segments (from samples.json if available, else all parsed)
    available_segments: list[tuple[str, int]] = []

    def _segment_passes_filters(list_id: str, seg_idx: int) -> bool:
        seg_id = f"{list_id}__{seg_idx}"
        if rec_filter != "All" and seg_id in all_judge_results:
            jr = all_judge_results[seg_id]
            if jr.get("recommendation") != rec_filter:
                return False
            if jr.get("score", 0.0) < min_score:
                return False

        if correction_filter != "All":
            # Load parse result to check correction_round
            from winerank.sft.wine_parser import load_parse_result
            pr = load_parse_result(settings.parsed_dir, list_id, seg_idx)
            if pr is None:
                return False
            is_corrected = pr.correction_round > 0
            if correction_filter == "Original only" and is_corrected:
                return False
            if correction_filter == "Corrected only" and not is_corrected:
                return False

        return True

    if samples:
        for s in samples:
            if _segment_passes_filters(s.list_id, s.segment_index):
                available_segments.append((s.list_id, s.segment_index))
    else:
        # Fallback: list all parsed results
        if settings.parsed_dir.exists():
            for f in sorted(settings.parsed_dir.glob("*.json")):
                parts = f.stem.rsplit("__", 1)
                if len(parts) == 2:
                    try:
                        lid, sidx = parts[0], int(parts[1])
                    except ValueError:
                        continue
                    if _segment_passes_filters(lid, sidx):
                        available_segments.append((lid, sidx))

    if not available_segments:
        st.info(
            "No segments found. Run `winerank sft-data parse` to generate parsed results, "
            "or adjust the filters."
        )
        return

    # Segment index selector
    st.sidebar.markdown(f"**{len(available_segments)} segments** match filters")
    seg_num = st.sidebar.number_input(
        "Segment #", min_value=1, max_value=len(available_segments), value=1, step=1
    )
    selected_list_id, selected_seg_idx = available_segments[seg_num - 1]

    # Aggregate stats sidebar
    if has_judge:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Judge Summary")
        counts = {"accept": 0, "review": 0, "reject": 0}
        scores = []
        corrected_total = 0
        for jr in all_judge_results.values():
            rec = jr.get("recommendation", "review")
            counts[rec] = counts.get(rec, 0) + 1
            scores.append(jr.get("score", 0.0))
            if jr.get("correction_round", 0) > 0:
                corrected_total += 1
        st.sidebar.metric("Accept", counts["accept"])
        st.sidebar.metric("Review", counts["review"])
        st.sidebar.metric("Reject", counts["reject"])
        if scores:
            st.sidebar.metric("Avg Score", f"{sum(scores)/len(scores):.3f}")
        if corrected_total:
            st.sidebar.metric("Corrected Segments", corrected_total)

    # ---------------------------------------------------------------------------
    # Main content: header row
    # ---------------------------------------------------------------------------
    parse_result = _load_parse_result(selected_list_id, selected_seg_idx)
    correction_round = parse_result.correction_round if parse_result else 0

    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        st.markdown(
            f"**List:** {list_names.get(selected_list_id, selected_list_id)}  |  "
            f"**Segment:** {selected_seg_idx}  |  "
            f"**ID:** `{selected_list_id}__{selected_seg_idx}`"
        )
    with col_hdr2:
        st.markdown(
            _render_correction_badge(correction_round),
            unsafe_allow_html=True,
        )

    taxonomy = _load_taxonomy(selected_list_id)
    judge_result_dict = all_judge_results.get(f"{selected_list_id}__{selected_seg_idx}")

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Three-column layout: original | taxonomy | parsed wines
    # ---------------------------------------------------------------------------
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        st.subheader("Original Segment")
        if parse_result:
            entry = manifest.get_entry(selected_list_id)
            source_file = parse_result.source_file if parse_result else (entry.file_path if entry else "")
            file_type = entry.file_type if entry else "pdf"

            if file_type == "pdf":
                rendered = _render_pdf_page_image(source_file, selected_seg_idx)
                if not rendered:
                    st.caption("(Page image unavailable - install pdf2image and poppler)")
            else:
                _render_html_segment(source_file, selected_seg_idx)

            st.markdown("**Extracted Text:**")
            st.text_area(
                "segment_text",
                parse_result.segment_text if parse_result else "",
                height=250,
                label_visibility="collapsed",
            )
        else:
            st.info("No extracted text available. Run `winerank sft-data parse`.")

    with col2:
        st.subheader("Taxonomy")
        _render_taxonomy_tree(taxonomy)

        if taxonomy and taxonomy.status == "OK" and taxonomy.categories:
            with st.expander("Flat category list"):
                for cat in taxonomy.flat_categories():
                    st.text(cat)

    with col3:
        st.subheader("Parsed Wines")
        _render_wines_table(parse_result)

        if parse_result and not parse_result.parse_error:
            with st.expander("Raw JSON"):
                wines_json = {"wines": [w.model_dump(exclude_none=True) for w in parse_result.wines]}
                st.json(wines_json)

            with st.expander("Token usage"):
                st.write(f"Input: {parse_result.input_tokens:,}")
                st.write(f"Output: {parse_result.output_tokens:,}")
                st.write(f"Cached: {parse_result.cached_tokens:,}")
                st.write(f"Model: {parse_result.model_used}")
                if correction_round > 0:
                    st.write(f"Correction round: {correction_round}")

    # ---------------------------------------------------------------------------
    # Judge review section (full width, collapsed by default)
    # ---------------------------------------------------------------------------
    st.markdown("---")

    if not has_judge:
        with st.expander("Judge Review (not run)", expanded=False):
            st.info(
                "No judge results available. "
                "Run `winerank sft-data judge` to score parsing quality."
            )
    else:
        with st.expander("Judge Review Results", expanded=True):
            if judge_result_dict is None:
                st.info("No judge result for this segment.")
            else:
                score = judge_result_dict.get("score", 0.0)
                rec = judge_result_dict.get("recommendation", "review")
                count_match = judge_result_dict.get("wine_count_match", False)
                needs_reparse = judge_result_dict.get("needs_reparse", False)
                issues = judge_result_dict.get("issues", [])
                judge_correction_round = judge_result_dict.get("correction_round", 0)

                # Score + recommendation + correction round header
                score_col, rec_col, count_col, round_col = st.columns(4)
                with score_col:
                    st.markdown(f"**Score:** {_render_score_badge(score)}", unsafe_allow_html=True)
                with rec_col:
                    st.markdown(
                        f"**Recommendation:** {_render_recommendation_pill(rec)}",
                        unsafe_allow_html=True,
                    )
                with count_col:
                    match_icon = "✅" if count_match else "❌"
                    st.markdown(f"**Wine Count Match:** {match_icon}")
                with round_col:
                    if needs_reparse:
                        st.markdown("**Needs Reparse:** ⚠️ Yes")
                    else:
                        st.markdown("**Needs Reparse:** ✅ No")

                if judge_correction_round > 0:
                    st.caption(f"Judged after correction round {judge_correction_round}")

                # Structured issues
                if issues:
                    st.markdown(f"**Issues flagged by Judge ({len(issues)}):**")
                    for issue in issues:
                        # Support both dict and JudgeIssue-like objects
                        if hasattr(issue, "model_dump"):
                            issue = issue.model_dump()
                        _render_issue_card(issue)
                else:
                    st.success("No issues flagged.")

                # Judge model info
                st.caption(f"Judge model: {judge_result_dict.get('model_used', 'N/A')}")
