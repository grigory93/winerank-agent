"""
Judge reviewer: optional LLM pass to review and score parsed wine segments.

For each parsed segment:
1. Build an LLMRequest with original text + taxonomy + parsed JSON (prepare phase)
2. Executor sends requests to the Judge model (execute phase)
3. Parse responses into JudgeResult, save to data/sft/judged/ (process phase)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.executor.types import LLMRequest, LLMResponse
from winerank.sft.page_reader import render_pdf_page_to_base64
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_judge_messages
from winerank.sft.schemas import JudgeIssue, JudgeResult, PageParseResult

logger = logging.getLogger(__name__)

_ANTHROPIC_CACHE_POINTS = [
    {"location": "system"},
    {"location": "message_content", "message_index": 1, "content_index": 0},
]


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or "anthropic" in model.lower()


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------

def prepare_judge_requests(
    parse_results: list[PageParseResult],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
) -> list[LLMRequest]:
    """
    Build LLMRequest objects for the judge review phase.

    Skips segments that already have judge results (unless force=True) and
    segments that have parse errors (they would not be useful training data).

    Args:
        parse_results: Parsed segment results from the Teacher model.
        settings: SFT configuration (judge model name, etc.).
        progress: Progress tracker for resume support.
        force: Re-run even if already completed.

    Returns:
        List of LLMRequest objects ready for executor.execute().
    """
    requests: list[LLMRequest] = []

    for parse_result in parse_results:
        list_id = parse_result.list_id
        seg_idx = parse_result.segment_index

        if not force and progress.is_judge_done(list_id, seg_idx):
            logger.debug("[%s] Segment %d already judged, skipping", list_id, seg_idx)
            continue

        if parse_result.parse_error:
            logger.warning("[%s] Segment %d has parse error, skipping judge", list_id, seg_idx)
            continue

        parsed_json = json.dumps(
            {"wines": [w.model_dump() for w in parse_result.wines]}, indent=2
        )

        image_b64: Optional[str] = None
        if settings.training_data_mode == "vision" and parse_result.source_file:
            source = Path(parse_result.source_file)
            if source.suffix.lower() == ".pdf":
                image_b64 = render_pdf_page_to_base64(source, seg_idx)

        messages = build_judge_messages(
            segment_text=parse_result.segment_text,
            taxonomy_text=parse_result.taxonomy_text,
            parsed_json=parsed_json,
            segment_image_b64=image_b64,
        )

        cache_points = _ANTHROPIC_CACHE_POINTS if _is_anthropic_model(settings.judge_model) else None

        requests.append(LLMRequest(
            custom_id=f"judge__{list_id}__{seg_idx}",
            model=settings.judge_model,
            messages=messages,
            max_tokens=2048,
            temperature=0.0,
            response_format={"type": "json_object"},
            cache_control_injection_points=cache_points,
        ))

    return requests


# ---------------------------------------------------------------------------
# Response processing
# ---------------------------------------------------------------------------

def process_judge_responses(
    responses: list[LLMResponse],
    settings: SFTSettings,
    progress: ProgressTracker,
    correction_round: int = 0,
) -> list[JudgeResult]:
    """
    Parse executor responses into JudgeResult objects and persist them.

    Args:
        responses: LLMResponse objects from executor.execute().
        settings: SFT configuration.
        progress: Progress tracker to update.
        correction_round: Which correction round produced the parsed output
            being judged (0 = original parse, 1+ = correction round).

    Returns:
        List of successfully parsed JudgeResult objects.
    """
    results: list[JudgeResult] = []

    for response in responses:
        # custom_id format: "judge__<list_id>__<seg_idx>"
        _, list_id, seg_idx_str = response.custom_id.split("__", 2)
        seg_idx = int(seg_idx_str)
        segment_id = f"{list_id}__{seg_idx}"

        if response.error:
            logger.error("[%s] Judge executor error for seg %d: %s",
                         list_id, seg_idx, response.error)
            progress.mark_judge_done(list_id, seg_idx, error=response.error)
            continue

        try:
            judge_result = _parse_judge_response(
                raw_text=response.content,
                segment_id=segment_id,
                list_id=list_id,
                segment_index=seg_idx,
                model=settings.judge_model,
                correction_round=correction_round,
            )
            judge_result.input_tokens = response.tokens.get("input", 0)
            judge_result.output_tokens = response.tokens.get("output", 0)
        except Exception as exc:
            logger.error("[%s] Judge response parse error for seg %d: %s",
                         list_id, seg_idx, exc)
            progress.mark_judge_done(list_id, seg_idx, error=str(exc))
            continue

        save_judge_result(judge_result, settings.judged_dir)
        progress.mark_judge_done(list_id, seg_idx, tokens=response.tokens)
        logger.info(
            "[%s] Segment %d: judge score=%.2f recommendation=%s (correction_round=%d)",
            list_id, seg_idx, judge_result.score, judge_result.recommendation, correction_round,
        )
        results.append(judge_result)

    return results


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------

def _parse_judge_response(
    raw_text: str,
    segment_id: str,
    list_id: str,
    segment_index: int,
    model: str,
    correction_round: int = 0,
) -> JudgeResult:
    """
    Parse the raw JSON response from the judge model into a JudgeResult.
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Judge returned invalid JSON: {exc}\nRaw: {raw_text[:500]}"
        ) from exc

    raw_issues = data.get("issues", [])

    return JudgeResult(
        segment_id=segment_id,
        list_id=list_id,
        segment_index=segment_index,
        score=float(data.get("score", 0.0)),
        wine_count_match=bool(data.get("wine_count_match", False)),
        issues=raw_issues,
        recommendation=data.get("recommendation", "review"),
        needs_reparse=bool(data.get("needs_reparse", False)),
        correction_round=correction_round,
        raw_response=raw_text,
        model_used=model,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_judge_result(result: JudgeResult, judged_dir: Path) -> Path:
    """Save a JudgeResult to the judged directory."""
    judged_dir.mkdir(parents=True, exist_ok=True)
    out_path = judged_dir / f"{result.segment_id}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result.model_dump(), fh, indent=2, ensure_ascii=False)
    return out_path


def load_judge_result(
    judged_dir: Path,
    list_id: str,
    segment_index: int,
) -> Optional[JudgeResult]:
    """Load a saved JudgeResult from disk."""
    path = judged_dir / f"{list_id}__{segment_index}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return JudgeResult(**data)


def load_all_judge_results(judged_dir: Path) -> dict[str, JudgeResult]:
    """Load all JudgeResult files; returns dict keyed by segment_id."""
    results: dict[str, JudgeResult] = {}
    if not judged_dir.exists():
        return results
    for p in sorted(judged_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            result = JudgeResult(**data)
            results[result.segment_id] = result
        except Exception as exc:
            logger.warning("Failed to load judge result %s: %s", p, exc)
    return results


# ---------------------------------------------------------------------------
# Convenience wrapper for individual sft-data judge command
# ---------------------------------------------------------------------------

def judge_all_segments(
    parse_results: list[PageParseResult],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> list[JudgeResult]:
    """
    Run judge review on all parsed segments using SyncExecutor.

    Convenience wrapper for the `sft-data judge` command.
    The full `sft-data run` orchestration uses prepare/execute/process directly.
    """
    from winerank.sft.executor.sync import SyncExecutor

    # Pre-load already-completed results
    completed = []
    pending = []
    for parse_result in parse_results:
        list_id = parse_result.list_id
        seg_idx = parse_result.segment_index
        if not force and progress.is_judge_done(list_id, seg_idx):
            r = load_judge_result(settings.judged_dir, list_id, seg_idx)
            if r:
                completed.append(r)
        else:
            pending.append(parse_result)

    if dry_run:
        for pr in pending:
            if not pr.parse_error:
                logger.info("[%s] DRY RUN: would call %s for judge on segment %d",
                            pr.list_id, settings.judge_model, pr.segment_index)
        return completed

    if not pending:
        return completed

    requests = prepare_judge_requests(pending, settings, progress, force=force)
    if not requests:
        return completed

    executor = SyncExecutor()
    responses = executor.execute(requests)
    new_results = process_judge_responses(responses, settings, progress)
    return completed + new_results
