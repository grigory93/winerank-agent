"""
Judge reviewer: optional LLM pass to review and score parsed wine segments.

For each parsed segment:
1. Send original text + taxonomy + parsed JSON to the Judge model
2. Judge returns score (0-1), wine_count_match, issues list, recommendation
3. Results saved to data/sft/judged/<list_id>__<segment_index>.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_judge_messages
from winerank.sft.schemas import JudgeResult, PageParseResult

logger = logging.getLogger(__name__)


def _call_judge_model(
    messages: list[dict],
    model: str,
    max_tokens: int = 2048,
) -> tuple[str, dict[str, int]]:
    """Call the judge model and return raw response + token counts."""
    import litellm  # type: ignore[import-untyped]

    response = litellm.completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw_text: str = response.choices[0].message.content or ""
    usage = response.usage or {}
    tokens = {
        "input": getattr(usage, "prompt_tokens", 0),
        "output": getattr(usage, "completion_tokens", 0),
        "cached": 0,
    }
    return raw_text, tokens


def _parse_judge_response(
    raw_text: str,
    segment_id: str,
    list_id: str,
    segment_index: int,
    model: str,
) -> JudgeResult:
    """Parse the raw JSON response from the judge model into a JudgeResult."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Judge returned invalid JSON: {e}\nRaw: {raw_text[:500]}")

    return JudgeResult(
        segment_id=segment_id,
        list_id=list_id,
        segment_index=segment_index,
        score=float(data.get("score", 0.0)),
        wine_count_match=bool(data.get("wine_count_match", False)),
        issues=data.get("issues", []),
        recommendation=data.get("recommendation", "review"),
        raw_response=raw_text,
        model_used=model,
    )


def judge_segment(
    parse_result: PageParseResult,
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> Optional[JudgeResult]:
    """
    Run judge review for a single parsed segment.

    Args:
        parse_result: The Teacher's parsed result for this segment.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run even if already completed.
        dry_run: Show what would happen without LLM calls.

    Returns:
        JudgeResult, or None on error/skip.
    """
    list_id = parse_result.list_id
    seg_idx = parse_result.segment_index
    segment_id = parse_result.segment_id

    if not force and progress.is_judge_done(list_id, seg_idx):
        logger.info("[%s] Segment %d already judged, skipping", list_id, seg_idx)
        return load_judge_result(settings.judged_dir, list_id, seg_idx)

    # Skip segments with parse errors
    if parse_result.parse_error:
        logger.warning("[%s] Segment %d has parse error, skipping judge", list_id, seg_idx)
        return None

    if dry_run:
        logger.info("[%s] DRY RUN: would call %s for judge on segment %d",
                    list_id, settings.judge_model, seg_idx)
        return None

    parsed_json = json.dumps({"wines": [w.model_dump() for w in parse_result.wines]}, indent=2)
    messages = build_judge_messages(
        segment_text=parse_result.segment_text,
        taxonomy_text=parse_result.taxonomy_text,
        parsed_json=parsed_json,
    )

    try:
        raw_text, tokens = _call_judge_model(messages, model=settings.judge_model)
        judge_result = _parse_judge_response(
            raw_text=raw_text,
            segment_id=segment_id,
            list_id=list_id,
            segment_index=seg_idx,
            model=settings.judge_model,
        )
        judge_result.input_tokens = tokens.get("input", 0)
        judge_result.output_tokens = tokens.get("output", 0)
    except Exception as e:
        logger.error("[%s] Judge model call failed for segment %d: %s", list_id, seg_idx, e)
        progress.mark_judge_done(list_id, seg_idx, error=str(e))
        return None

    save_judge_result(judge_result, settings.judged_dir)
    progress.mark_judge_done(list_id, seg_idx, tokens=tokens)
    logger.info(
        "[%s] Segment %d: judge score=%.2f recommendation=%s",
        list_id, seg_idx, judge_result.score, judge_result.recommendation,
    )
    return judge_result


def save_judge_result(result: JudgeResult, judged_dir: Path) -> Path:
    """Save a JudgeResult to the judged directory."""
    judged_dir.mkdir(parents=True, exist_ok=True)
    out_path = judged_dir / f"{result.segment_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
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
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return JudgeResult(**data)


def load_all_judge_results(judged_dir: Path) -> dict[str, JudgeResult]:
    """Load all JudgeResult files; returns dict keyed by segment_id."""
    results: dict[str, JudgeResult] = {}
    if not judged_dir.exists():
        return results
    for p in sorted(judged_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            result = JudgeResult(**data)
            results[result.segment_id] = result
        except Exception as e:
            logger.warning("Failed to load judge result %s: %s", p, e)
    return results


def judge_all_segments(
    parse_results: list[PageParseResult],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> list[JudgeResult]:
    """
    Run judge review on all parsed segments.

    Args:
        parse_results: All Teacher-parsed segment results.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run already-completed judgements.
        dry_run: Show what would happen without LLM calls.

    Returns:
        List of JudgeResult objects.
    """
    results = []
    for parse_result in parse_results:
        result = judge_segment(
            parse_result=parse_result,
            settings=settings,
            progress=progress,
            force=force,
            dry_run=dry_run,
        )
        if result is not None:
            results.append(result)
    return results
