"""
Wine parser: parse wine entries from segments using the powerful Teacher model.

Key features:
- Injects taxonomy as VALID CATEGORIES enum in the prompt
- Prompt caching enabled (Anthropic ephemeral cache via LLMRequest, OpenAI automatic)
- Pydantic validation of parsed wine entries
- Saves results to data/sft/parsed/<list_id>__<segment_index>.json
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
from winerank.sft.prompts import build_wine_parsing_messages
from winerank.sft.schemas import (
    PageParseResult,
    SampleManifestEntry,
    TaxonomyResult,
    WineEntry,
)
from winerank.sft.taxonomy_extractor import load_taxonomy

logger = logging.getLogger(__name__)

# Cache control injection points for Anthropic models:
# system message (schema + rules) and first user content block (taxonomy) are
# stable across all segments of the same list -- caching reduces them by ~90%.
_ANTHROPIC_CACHE_POINTS = [
    {"location": "system"},
    {"location": "message_content", "message_index": 1, "content_index": 0},
]


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or "anthropic" in model.lower()


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------

def prepare_parse_requests(
    samples: list[SampleManifestEntry],
    taxonomies: dict[str, Optional[TaxonomyResult]],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
) -> list[LLMRequest]:
    """
    Build LLMRequest objects for the wine parsing phase.

    Each request carries the full parsing prompt (system schema + taxonomy +
    segment text). Anthropic requests include cache_control_injection_points
    so the SyncExecutor / BatchExecutor can inject caching markers.

    Args:
        samples: Sampled segment references from samples.json.
        taxonomies: Pre-loaded taxonomy results keyed by list_id.
        settings: SFT configuration (teacher model, mode, etc.).
        progress: Progress tracker for resume support.
        force: Re-run even if already completed.

    Returns:
        List of LLMRequest objects, one per segment to parse.
    """
    requests: list[LLMRequest] = []

    for sample in samples:
        list_id = sample.list_id
        seg_idx = sample.segment_index

        if not force and progress.is_parse_done(list_id, seg_idx):
            logger.debug("[%s] Segment %d already parsed, skipping", list_id, seg_idx)
            continue

        segment_text = _get_segment_text(sample, min_chars=settings.min_segment_chars)
        if not segment_text:
            logger.warning("[%s] Could not retrieve segment %d text", list_id, seg_idx)
            progress.mark_parse_done(list_id, seg_idx, error="Segment text not found")
            continue

        taxonomy = taxonomies.get(list_id)
        taxonomy_text = (
            taxonomy.to_prompt_text()
            if taxonomy and taxonomy.status == "OK"
            else "(no taxonomy available)"
        )

        image_b64: Optional[str] = None
        if settings.training_data_mode == "vision" and sample.file_type == "pdf":
            image_b64 = render_pdf_page_to_base64(Path(sample.source_file), seg_idx)

        messages = build_wine_parsing_messages(
            taxonomy_text=taxonomy_text,
            segment_text=segment_text,
            segment_image_b64=image_b64,
        )

        cache_points = _ANTHROPIC_CACHE_POINTS if _is_anthropic_model(settings.teacher_model) else None

        requests.append(LLMRequest(
            custom_id=f"parse__{list_id}__{seg_idx}",
            model=settings.teacher_model,
            messages=messages,
            max_tokens=8192,
            temperature=0.0,
            response_format={"type": "json_object"},
            cache_control_injection_points=cache_points,
        ))

    return requests


# ---------------------------------------------------------------------------
# Response processing
# ---------------------------------------------------------------------------

def process_parse_responses(
    responses: list[LLMResponse],
    samples_by_id: dict[str, SampleManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
) -> list[PageParseResult]:
    """
    Parse executor responses into PageParseResult objects and persist them.

    Args:
        responses: LLMResponse objects from executor.execute().
        samples_by_id: Dict mapping custom_id -> SampleManifestEntry for
            retrieving segment metadata.
        settings: SFT configuration.
        progress: Progress tracker to update.

    Returns:
        List of PageParseResult objects (including error results).
    """
    results: list[PageParseResult] = []

    for response in responses:
        # custom_id format: "parse__<list_id>__<seg_idx>"
        _, list_id, seg_idx_str = response.custom_id.split("__", 2)
        seg_idx = int(seg_idx_str)
        segment_id = f"{list_id}__{seg_idx}"

        sample = samples_by_id.get(response.custom_id)
        segment_text = sample and _get_segment_text(sample, settings.min_segment_chars) or ""
        taxonomy_text = ""

        # Retrieve taxonomy text for this list if available
        tax = load_taxonomy(settings.taxonomy_dir, list_id)
        if tax and tax.status == "OK":
            taxonomy_text = tax.to_prompt_text()

        if response.error:
            logger.error("[%s] Parse executor error for seg %d: %s",
                         list_id, seg_idx, response.error)
            result = PageParseResult(
                segment_id=segment_id,
                list_id=list_id,
                segment_index=seg_idx,
                source_file=sample.source_file if sample else "",
                segment_text=segment_text,
                taxonomy_text=taxonomy_text,
                wines=[],
                parse_error=response.error,
                model_used=settings.teacher_model,
            )
            save_parse_result(result, settings.parsed_dir)
            progress.mark_parse_done(list_id, seg_idx, error=response.error)
            results.append(result)
            continue

        try:
            wines = _parse_wines_from_response(response.content)
            parse_error = None
        except Exception as exc:
            logger.error("[%s] Parse response validation failed for seg %d: %s",
                         list_id, seg_idx, exc)
            wines = []
            parse_error = str(exc)

        result = PageParseResult(
            segment_id=segment_id,
            list_id=list_id,
            segment_index=seg_idx,
            source_file=sample.source_file if sample else "",
            segment_text=segment_text,
            taxonomy_text=taxonomy_text,
            wines=wines,
            raw_response=response.content if not parse_error else None,
            parse_error=parse_error,
            input_tokens=response.tokens.get("input", 0),
            output_tokens=response.tokens.get("output", 0),
            cached_tokens=response.tokens.get("cached", 0),
            model_used=settings.teacher_model,
        )
        save_parse_result(result, settings.parsed_dir)
        progress.mark_parse_done(list_id, seg_idx,
                                  tokens=response.tokens,
                                  error=parse_error)
        logger.info("[%s] Segment %d: parsed %d wines (%d cached tokens)",
                    list_id, seg_idx, len(wines), response.tokens.get("cached", 0))
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_wines_from_response(raw_text: str) -> list[WineEntry]:
    """Parse and validate wine entries from raw LLM JSON response."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model returned invalid JSON: {exc}\nRaw: {raw_text[:500]}"
        ) from exc

    wines_data = data.get("wines", [])
    if not isinstance(wines_data, list):
        raise ValueError(f"Expected 'wines' list, got: {type(wines_data)}")

    wines: list[WineEntry] = []
    for item in wines_data:
        if not isinstance(item, dict):
            continue
        try:
            wines.append(WineEntry(**item))
        except Exception as exc:
            logger.warning("Skipping invalid wine entry %s: %s", item, exc)
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
    except Exception as exc:
        logger.error("[%s] Failed to re-extract segment %d: %s",
                     sample.list_id, sample.segment_index, exc)
        return None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_parse_result(result: PageParseResult, parsed_dir: Path) -> Path:
    """Save a PageParseResult to the parsed directory."""
    parsed_dir.mkdir(parents=True, exist_ok=True)
    out_path = parsed_dir / f"{result.segment_id}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result.model_dump(), fh, indent=2, ensure_ascii=False)
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
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return PageParseResult(**data)


def load_all_parse_results(parsed_dir: Path) -> list[PageParseResult]:
    """Load all PageParseResult files from the parsed directory."""
    results = []
    for p in sorted(parsed_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            results.append(PageParseResult(**data))
        except Exception as exc:
            logger.warning("Failed to load parse result %s: %s", p, exc)
    return results


# ---------------------------------------------------------------------------
# Convenience wrapper for individual sft-data parse command
# ---------------------------------------------------------------------------

def parse_all_segments(
    samples: list[SampleManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> list[PageParseResult]:
    """
    Parse all sampled segments with the Teacher model using SyncExecutor.

    Convenience wrapper for the `sft-data parse` command.
    The full `sft-data run` orchestration uses prepare/execute/process directly.
    """
    from winerank.sft.executor.sync import SyncExecutor

    # Load already-completed results
    results = []
    pending_samples = []
    for sample in samples:
        if not force and progress.is_parse_done(sample.list_id, sample.segment_index):
            r = load_parse_result(settings.parsed_dir, sample.list_id, sample.segment_index)
            if r:
                results.append(r)
        else:
            pending_samples.append(sample)

    if dry_run:
        for sample in pending_samples:
            logger.info("[%s] DRY RUN: would call %s for segment %d",
                        sample.list_id, settings.teacher_model, sample.segment_index)
        return results

    if not pending_samples:
        return results

    # Load all taxonomies once
    taxonomies: dict[str, Optional[TaxonomyResult]] = {}
    for sample in pending_samples:
        if sample.list_id not in taxonomies:
            taxonomies[sample.list_id] = load_taxonomy(settings.taxonomy_dir, sample.list_id)

    requests = prepare_parse_requests(
        pending_samples, taxonomies, settings, progress, force=force
    )
    if not requests:
        return results

    samples_by_id = {
        f"parse__{s.list_id}__{s.segment_index}": s for s in pending_samples
    }
    executor = SyncExecutor()
    responses = executor.execute(requests)
    new_results = process_parse_responses(responses, samples_by_id, settings, progress)
    results.extend(new_results)
    return results
