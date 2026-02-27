"""
Corrector: closed-loop correction pass using Judge feedback.

For each segment the Judge flagged as "review" or "reject":
1. Build a correction LLMRequest (Teacher model) that includes:
   - Original segment text + taxonomy (same as initial parse -- cacheable prefix)
   - Teacher's previous parsed JSON
   - Judge's structured issues list
2. Executor sends correction requests (batch or sync)
3. Parse corrected wines, overwrite the result in data/sft/parsed/

This is Phase 3.6 of the pipeline. Phase 3.7 is a re-judge pass on the
corrected results, which reuses prepare_judge_requests / process_judge_responses
from judge_reviewer.py with force=True on the corrected segments.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.executor.types import LLMRequest, LLMResponse
from winerank.sft.page_reader import extract_segments, render_pdf_page_to_base64
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_correction_messages
from winerank.sft.schemas import (
    JudgeResult,
    PageParseResult,
    SampleManifestEntry,
    TaxonomyResult,
    WineEntry,
)
from winerank.sft.taxonomy_extractor import load_taxonomy
from winerank.sft.wine_parser import (
    _ANTHROPIC_CACHE_POINTS,
    _is_anthropic_model,
    _parse_wines_from_response,
    save_parse_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------


def prepare_correction_requests(
    parse_results: list[PageParseResult],
    judge_results: dict[str, JudgeResult],
    taxonomies: dict[str, Optional[TaxonomyResult]],
    settings: SFTSettings,
    progress: ProgressTracker,
    round_num: int,
    force: bool = False,
) -> list[LLMRequest]:
    """
    Build LLMRequest objects for the correction phase.

    Only segments where the Judge flagged "review" or "reject" (or
    needs_reparse=True) are included. Already-corrected segments (in this
    round) are skipped unless force=True.

    Args:
        parse_results: Current parsed results (may be from a previous correction round).
        judge_results: Judge review results keyed by segment_id.
        taxonomies: Pre-loaded taxonomy results keyed by list_id.
        settings: SFT configuration (teacher model, mode, etc.).
        progress: Progress tracker for resume support.
        round_num: Current correction round number (1-indexed).
        force: Re-run even if already completed.

    Returns:
        List of LLMRequest objects ready for executor.execute().
    """
    requests: list[LLMRequest] = []

    for parse_result in parse_results:
        list_id = parse_result.list_id
        seg_idx = parse_result.segment_index
        segment_id = parse_result.segment_id

        judge = judge_results.get(segment_id)
        if judge is None:
            continue

        # Only correct segments the Judge flagged
        if judge.recommendation == "accept" and not judge.needs_reparse:
            continue

        if not force and progress.is_correction_done(list_id, seg_idx, round_num):
            logger.debug(
                "[%s] Segment %d already corrected in round %d, skipping",
                list_id, seg_idx, round_num,
            )
            continue

        # Build previous JSON from the parse result
        previous_json = json.dumps(
            {"wines": [w.model_dump(exclude_none=True) for w in parse_result.wines]},
            indent=2,
        )

        taxonomy = taxonomies.get(list_id)
        taxonomy_text = (
            taxonomy.to_prompt_text()
            if taxonomy and taxonomy.status == "OK"
            else "(no taxonomy available)"
        )

        segment_text = parse_result.segment_text
        if not segment_text:
            logger.warning(
                "[%s] Segment %d has no text for correction, skipping", list_id, seg_idx
            )
            continue

        image_b64: Optional[str] = None
        if settings.training_data_mode == "vision" and parse_result.source_file:
            source = Path(parse_result.source_file)
            if source.suffix.lower() == ".pdf":
                image_b64 = render_pdf_page_to_base64(source, seg_idx)

        messages = build_correction_messages(
            taxonomy_text=taxonomy_text,
            segment_text=segment_text,
            previous_json=previous_json,
            issues=judge.issues,
            segment_image_b64=image_b64,
        )

        cache_points = _ANTHROPIC_CACHE_POINTS if _is_anthropic_model(settings.teacher_model) else None

        requests.append(LLMRequest(
            custom_id=f"correct__{list_id}__{seg_idx}__{round_num}",
            model=settings.teacher_model,
            messages=messages,
            max_tokens=8192,
            temperature=0.0,
            response_format={"type": "json_object"},
            cache_control_injection_points=cache_points,
        ))

    logger.info(
        "Correction round %d: prepared %d requests", round_num, len(requests)
    )
    return requests


# ---------------------------------------------------------------------------
# Response processing
# ---------------------------------------------------------------------------


def process_correction_responses(
    responses: list[LLMResponse],
    parse_results_by_id: dict[str, PageParseResult],
    settings: SFTSettings,
    progress: ProgressTracker,
    round_num: int,
) -> list[PageParseResult]:
    """
    Parse correction responses and overwrite parsed results on disk.

    The corrected PageParseResult replaces the original in data/sft/parsed/
    so that Phase 4 (build_dataset) automatically picks up corrected versions.

    Args:
        responses: LLMResponse objects from executor.execute().
        parse_results_by_id: Dict mapping segment_id -> PageParseResult for
            retrieving segment metadata.
        settings: SFT configuration.
        progress: Progress tracker to update.
        round_num: Current correction round number.

    Returns:
        List of corrected PageParseResult objects.
    """
    corrected: list[PageParseResult] = []

    for response in responses:
        # custom_id format: "correct__<list_id>__<seg_idx>__<round_num>"
        parts = response.custom_id.split("__", 3)
        if len(parts) != 4:
            logger.error("Unexpected correction custom_id format: %s", response.custom_id)
            continue
        _, list_id, seg_idx_str, _ = parts
        seg_idx = int(seg_idx_str)
        segment_id = f"{list_id}__{seg_idx}"

        original = parse_results_by_id.get(segment_id)

        if response.error:
            logger.error(
                "[%s] Correction executor error for seg %d round %d: %s",
                list_id, seg_idx, round_num, response.error,
            )
            progress.mark_correction_done(list_id, seg_idx, round_num, error=response.error)
            continue

        try:
            wines = _parse_wines_from_response(response.content)
            parse_error = None
        except Exception as exc:
            logger.error(
                "[%s] Correction response parse failed for seg %d round %d: %s",
                list_id, seg_idx, round_num, exc,
            )
            wines = []
            parse_error = str(exc)

        # Build corrected result, preserving original metadata
        corrected_result = PageParseResult(
            segment_id=segment_id,
            list_id=list_id,
            segment_index=seg_idx,
            source_file=original.source_file if original else "",
            segment_text=original.segment_text if original else "",
            taxonomy_text=original.taxonomy_text if original else "",
            wines=wines,
            raw_response=response.content if not parse_error else None,
            parse_error=parse_error,
            input_tokens=response.tokens.get("input", 0),
            output_tokens=response.tokens.get("output", 0),
            cached_tokens=response.tokens.get("cached", 0),
            model_used=settings.teacher_model,
            correction_round=round_num,
        )

        # Overwrite original parsed result on disk
        save_parse_result(corrected_result, settings.parsed_dir)
        progress.mark_correction_done(
            list_id, seg_idx, round_num, tokens=response.tokens, error=parse_error
        )

        if not parse_error:
            logger.info(
                "[%s] Segment %d corrected (round %d): %d wines (%d cached tokens)",
                list_id, seg_idx, round_num, len(wines),
                response.tokens.get("cached", 0),
            )
        corrected.append(corrected_result)

    return corrected
