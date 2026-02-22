"""
Taxonomy extractor: validate wine lists and extract hierarchical taxonomy.

For each wine list:
1. Extract full text (PDF or HTML)
2. Send full text to cheap Teacher model
3. Model first validates if text is a wine list (NOT_A_LIST gate)
4. If valid, extracts/infers a hierarchical wine category taxonomy
5. Saves result to data/sft/taxonomy/<list_id>.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.page_reader import extract_fulltext
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_taxonomy_prompt
from winerank.sft.schemas import ManifestEntry, TaxonomyNode, TaxonomyResult

logger = logging.getLogger(__name__)


def _call_taxonomy_model(
    full_text: str,
    model: str,
    max_tokens: int = 4096,
) -> tuple[str, dict[str, int]]:
    """
    Call the taxonomy model and return raw response text + token counts.

    Returns:
        Tuple of (raw_response_text, token_counts_dict)
    """
    import litellm  # type: ignore[import-untyped]

    messages = build_taxonomy_prompt(full_text)
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
        "cached": getattr(usage, "prompt_tokens_details", None)
        and getattr(usage.prompt_tokens_details, "cached_tokens", 0)
        or 0,
    }
    return raw_text, tokens


def _parse_taxonomy_response(
    raw_text: str,
    source_file: str,
) -> TaxonomyResult:
    """Parse the raw JSON response from the taxonomy model."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Taxonomy model returned invalid JSON: {e}\nRaw: {raw_text[:500]}")

    status = data.get("status", "OK")
    if status == "NOT_A_LIST":
        return TaxonomyResult(status="NOT_A_LIST", source_file=source_file)

    # Parse nested categories
    def parse_node(node_data: dict) -> TaxonomyNode:
        subs = [parse_node(s) for s in node_data.get("subcategories", [])]
        return TaxonomyNode(name=node_data.get("name", ""), subcategories=subs)

    categories = [parse_node(c) for c in data.get("categories", [])]
    return TaxonomyResult(
        status="OK",
        restaurant_name=data.get("restaurant_name"),
        categories=categories,
        source_file=source_file,
    )


def save_taxonomy(result: TaxonomyResult, taxonomy_dir: Path, list_id: str) -> Path:
    """Save a TaxonomyResult to JSON in the taxonomy directory."""
    taxonomy_dir.mkdir(parents=True, exist_ok=True)
    out_path = taxonomy_dir / f"{list_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
    return out_path


def load_taxonomy(taxonomy_dir: Path, list_id: str) -> Optional[TaxonomyResult]:
    """Load a saved TaxonomyResult from disk, or None if not found."""
    path = taxonomy_dir / f"{list_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def parse_node(n: dict) -> TaxonomyNode:
        return TaxonomyNode(
            name=n["name"],
            subcategories=[parse_node(s) for s in n.get("subcategories", [])],
        )

    categories = [parse_node(c) for c in data.get("categories", [])]
    return TaxonomyResult(
        status=data["status"],
        restaurant_name=data.get("restaurant_name"),
        categories=categories,
        source_file=data.get("source_file"),
    )


def extract_taxonomy_for_list(
    entry: ManifestEntry,
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> Optional[TaxonomyResult]:
    """
    Run taxonomy extraction for a single wine list.

    Args:
        entry: ManifestEntry for this wine list.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run even if already completed.
        dry_run: Show what would happen without making LLM calls.

    Returns:
        TaxonomyResult, or None on error.
    """
    list_id = entry.list_id
    file_path = Path(entry.file_path)

    if not force and progress.is_taxonomy_done(list_id):
        logger.info("[%s] Taxonomy already done (status=%s), skipping",
                    list_id, progress.get_taxonomy_status(list_id))
        return load_taxonomy(settings.taxonomy_dir, list_id)

    if not file_path.exists():
        logger.warning("[%s] File not found: %s", list_id, file_path)
        progress.mark_taxonomy_done(list_id, "ERROR", error=f"File not found: {file_path}")
        return None

    if dry_run:
        logger.info("[%s] DRY RUN: would call %s for taxonomy", list_id, settings.taxonomy_model)
        return None

    logger.info("[%s] Extracting taxonomy from %s", list_id, file_path.name)

    try:
        full_text = extract_fulltext(file_path)
    except Exception as e:
        logger.error("[%s] Text extraction failed: %s", list_id, e)
        progress.mark_taxonomy_done(list_id, "ERROR", error=str(e))
        return None

    try:
        raw_text, tokens = _call_taxonomy_model(full_text, model=settings.taxonomy_model)
        result = _parse_taxonomy_response(raw_text, source_file=str(file_path))
    except Exception as e:
        logger.error("[%s] Taxonomy model call failed: %s", list_id, e)
        progress.mark_taxonomy_done(list_id, "ERROR", error=str(e))
        return None

    save_taxonomy(result, settings.taxonomy_dir, list_id)
    progress.mark_taxonomy_done(list_id, result.status, tokens=tokens)

    if result.status == "NOT_A_LIST":
        logger.info("[%s] Marked as NOT_A_LIST", list_id)
    else:
        cat_count = len(result.flat_categories())
        logger.info("[%s] Taxonomy OK: %d categories", list_id, cat_count)

    return result


def extract_taxonomy_for_all(
    entries: list[ManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Optional[TaxonomyResult]]:
    """
    Run taxonomy extraction for all wine lists in the manifest.

    Args:
        entries: List of ManifestEntry items.
        settings: SFT settings.
        progress: ProgressTracker instance.
        force: Re-run even if already completed.
        dry_run: Show what would happen without making LLM calls.

    Returns:
        Dict mapping list_id -> TaxonomyResult (or None on error/skip).
    """
    results: dict[str, Optional[TaxonomyResult]] = {}
    for entry in entries:
        results[entry.list_id] = extract_taxonomy_for_list(
            entry, settings=settings, progress=progress, force=force, dry_run=dry_run
        )
    return results
