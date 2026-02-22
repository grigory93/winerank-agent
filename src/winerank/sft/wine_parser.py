"""
Wine parser: parse wine entries from segments using the powerful Teacher model.

Key features:
- Injects taxonomy as VALID CATEGORIES enum in the prompt
- Prompt caching enabled (Anthropic ephemeral cache, OpenAI automatic)
- Pydantic validation of parsed wine entries
- Saves results to data/sft/parsed/<list_id>__<segment_index>.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.page_reader import extract_segments, render_pdf_page_to_base64
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_wine_parsing_messages
from winerank.sft.schemas import (
    PageParseResult,
    SampleManifestEntry,
    TaxonomyResult,
    WineEntry,
)
from winerank.sft.taxonomy_extractor import load_taxonomy

logger = logging.getLogger(__name__)


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or "anthropic" in model.lower()


def _call_parsing_model(
    messages: list[dict],
    model: str,
    max_tokens: int = 8192,
) -> tuple[str, dict[str, int]]:
    """
    Call the wine parsing model with prompt caching enabled.

    For Anthropic models: uses cache_control_injection_points to cache the
    system message and the taxonomy (first user content block).
    For OpenAI models: prefix caching is automatic when prompts share a prefix.

    Returns:
        Tuple of (raw_response_text, token_counts_dict)
    """
    import litellm  # type: ignore[import-untyped]

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    if _is_anthropic_model(model):
        # Inject cache_control on system message and first user content block
        # so that repeated taxonomy + system tokens are cached (~90% cheaper)
        kwargs["cache_control_injection_points"] = [
            {"location": "system"},
            {"location": "message_content", "message_index": 1, "content_index": 0},
        ]

    response = litellm.completion(**kwargs)
    raw_text: str = response.choices[0].message.content or ""
    usage = response.usage or {}

    cached = 0
    if _is_anthropic_model(model):
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cached = int(cache_read)
    else:
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            cached = getattr(details, "cached_tokens", 0) or 0

    tokens = {
        "input": getattr(usage, "prompt_tokens", 0),
        "output": getattr(usage, "completion_tokens", 0),
        "cached": cached,
    }
    return raw_text, tokens


def _parse_wines_from_response(raw_text: str) -> list[WineEntry]:
    """Parse and validate wine entries from raw LLM JSON response."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}\nRaw: {raw_text[:500]}")

    wines_data = data.get("wines", [])
    if not isinstance(wines_data, list):
        raise ValueError(f"Expected 'wines' list, got: {type(wines_data)}")

    wines: list[WineEntry] = []
    for item in wines_data:
        if not isinstance(item, dict):
            continue
        try:
            wines.append(WineEntry(**item))
        except Exception as e:
            logger.warning("Skipping invalid wine entry %s: %s", item, e)
    return wines


def _get_segment_text(
    sample: SampleManifestEntry,
    min_chars: int = 50,
) -> Optional[str]:
    """Re-extract the specific segment text for a sample."""
    file_path = Path(sample.source_file)
    if not file_path.exists():
        return None
    try:
        all_segs = extract_segments(file_path, list_id=sample.list_id, min_chars=min_chars)
        for seg in all_segs:
            if seg.segment_index == sample.segment_index:
                return seg.segment_text
        return None
    except Exception as e:
        logger.error("[%s] Failed to re-extract segment %d: %s",
                     sample.list_id, sample.segment_index, e)
        return None


def parse_segment(
    sample: SampleManifestEntry,
    taxonomy: Optional[TaxonomyResult],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> Optional[PageParseResult]:
    """
    Parse wines from a single segment using the Teacher model.

    Args:
        sample: Reference to the segment to parse.
        taxonomy: Pre-extracted taxonomy for this wine list.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run even if already completed.
        dry_run: Show what would happen without making LLM calls.

    Returns:
        PageParseResult, or None on error.
    """
    list_id = sample.list_id
    seg_idx = sample.segment_index
    segment_id = f"{list_id}__{seg_idx}"

    if not force and progress.is_parse_done(list_id, seg_idx):
        logger.info("[%s] Segment %d already parsed, skipping", list_id, seg_idx)
        return load_parse_result(settings.parsed_dir, list_id, seg_idx)

    segment_text = _get_segment_text(sample, min_chars=settings.min_segment_chars)
    if not segment_text:
        logger.warning("[%s] Could not retrieve segment %d text", list_id, seg_idx)
        progress.mark_parse_done(list_id, seg_idx, error="Segment text not found")
        return None

    taxonomy_text = taxonomy.to_prompt_text() if taxonomy and taxonomy.status == "OK" else "(no taxonomy available)"

    if dry_run:
        logger.info("[%s] DRY RUN: would call %s for segment %d",
                    list_id, settings.teacher_model, seg_idx)
        return None

    # Vision mode: load page image
    image_b64: Optional[str] = None
    if settings.training_data_mode == "vision" and sample.file_type == "pdf":
        image_b64 = render_pdf_page_to_base64(Path(sample.source_file), seg_idx)

    messages = build_wine_parsing_messages(
        taxonomy_text=taxonomy_text,
        segment_text=segment_text,
        segment_image_b64=image_b64,
    )

    try:
        raw_text, tokens = _call_parsing_model(messages, model=settings.teacher_model)
        wines = _parse_wines_from_response(raw_text)
        parse_error = None
    except Exception as e:
        logger.error("[%s] Parsing model call failed for segment %d: %s", list_id, seg_idx, e)
        progress.mark_parse_done(list_id, seg_idx, error=str(e))
        result = PageParseResult(
            segment_id=segment_id,
            list_id=list_id,
            segment_index=seg_idx,
            source_file=sample.source_file,
            segment_text=segment_text,
            taxonomy_text=taxonomy_text,
            wines=[],
            parse_error=str(e),
            model_used=settings.teacher_model,
        )
        save_parse_result(result, settings.parsed_dir)
        return result

    result = PageParseResult(
        segment_id=segment_id,
        list_id=list_id,
        segment_index=seg_idx,
        source_file=sample.source_file,
        segment_text=segment_text,
        taxonomy_text=taxonomy_text,
        wines=wines,
        raw_response=raw_text,
        input_tokens=tokens.get("input", 0),
        output_tokens=tokens.get("output", 0),
        cached_tokens=tokens.get("cached", 0),
        model_used=settings.teacher_model,
    )
    save_parse_result(result, settings.parsed_dir)
    progress.mark_parse_done(list_id, seg_idx, tokens=tokens)
    logger.info("[%s] Segment %d: parsed %d wines (%d cached tokens)",
                list_id, seg_idx, len(wines), tokens.get("cached", 0))
    return result


def save_parse_result(result: PageParseResult, parsed_dir: Path) -> Path:
    """Save a PageParseResult to the parsed directory."""
    parsed_dir.mkdir(parents=True, exist_ok=True)
    out_path = parsed_dir / f"{result.segment_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
    return out_path


def load_parse_result(
    parsed_dir: Path,
    list_id: str,
    segment_index: int,
) -> Optional[PageParseResult]:
    """Load a saved PageParseResult from disk."""
    path = parsed_dir / f"{list_id}__{segment_index}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return PageParseResult(**data)


def load_all_parse_results(parsed_dir: Path) -> list[PageParseResult]:
    """Load all PageParseResult files from the parsed directory."""
    results = []
    for p in sorted(parsed_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            results.append(PageParseResult(**data))
        except Exception as e:
            logger.warning("Failed to load parse result %s: %s", p, e)
    return results


def parse_all_segments(
    samples: list[SampleManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> list[PageParseResult]:
    """
    Parse all sampled segments with the Teacher model.

    Args:
        samples: List of sampled segment references.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run already-completed segments.
        dry_run: Show what would happen without LLM calls.

    Returns:
        List of PageParseResult objects.
    """
    results = []
    for sample in samples:
        taxonomy = load_taxonomy(settings.taxonomy_dir, sample.list_id)
        result = parse_segment(
            sample=sample,
            taxonomy=taxonomy,
            settings=settings,
            progress=progress,
            force=force,
            dry_run=dry_run,
        )
        if result is not None:
            results.append(result)
    return results
