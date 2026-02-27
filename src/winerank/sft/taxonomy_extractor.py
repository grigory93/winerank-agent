"""
Taxonomy extractor: validate wine lists and extract hierarchical taxonomy.

For each wine list:
1. Extract full text (PDF or HTML)
2. Build an LLMRequest containing the full text (prepare phase)
3. Executor sends the request to the cheap taxonomy model (execute phase)
4. Parse the response, save result to data/sft/taxonomy/<list_id>.json (process phase)

The taxonomy model first validates whether the document is a wine list
(NOT_A_LIST gate) and, if valid, extracts/infers a hierarchical taxonomy.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.executor.types import LLMRequest, LLMResponse
from winerank.sft.page_reader import extract_fulltext
from winerank.sft.progress import ProgressTracker
from winerank.sft.prompts import build_taxonomy_prompt
from winerank.sft.schemas import ManifestEntry, TaxonomyNode, TaxonomyResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------

def prepare_taxonomy_requests(
    entries: list[ManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
) -> list[LLMRequest]:
    """
    Build LLMRequest objects for the taxonomy extraction phase.

    Skips entries that are already completed (unless force=True) or whose
    source files cannot be found. Returns one LLMRequest per entry that
    needs processing.

    Args:
        entries: Wine list manifest entries to process.
        settings: SFT configuration (taxonomy model name, etc.).
        progress: Progress tracker for resume support.
        force: Re-run even if already completed.

    Returns:
        List of LLMRequest objects ready for executor.execute().
    """
    requests: list[LLMRequest] = []

    for entry in entries:
        list_id = entry.list_id
        file_path = Path(entry.file_path)

        if not force and progress.is_taxonomy_done(list_id):
            logger.info("[%s] Taxonomy already done (status=%s), skipping",
                        list_id, progress.get_taxonomy_status(list_id))
            continue

        if not file_path.exists():
            logger.warning("[%s] File not found: %s", list_id, file_path)
            progress.mark_taxonomy_done(list_id, "ERROR",
                                        error=f"File not found: {file_path}")
            continue

        try:
            full_text = extract_fulltext(file_path)
        except Exception as exc:
            logger.error("[%s] Text extraction failed: %s", list_id, exc)
            progress.mark_taxonomy_done(list_id, "ERROR", error=str(exc))
            continue

        messages = build_taxonomy_prompt(full_text)
        requests.append(LLMRequest(
            custom_id=f"taxonomy__{list_id}",
            model=settings.taxonomy_model,
            messages=messages,
            max_tokens=4096,
            temperature=0.0,
            response_format={"type": "json_object"},
        ))
        logger.debug("[%s] Prepared taxonomy request", list_id)

    return requests


# ---------------------------------------------------------------------------
# Response processing
# ---------------------------------------------------------------------------

def process_taxonomy_responses(
    responses: list[LLMResponse],
    settings: SFTSettings,
    progress: ProgressTracker,
    entries_by_id: dict[str, ManifestEntry] | None = None,
) -> dict[str, TaxonomyResult]:
    """
    Parse executor responses and persist taxonomy results.

    Args:
        responses: LLMResponse objects from executor.execute().
        settings: SFT configuration (taxonomy directory path).
        progress: Progress tracker to update with completion status.
        entries_by_id: Optional dict mapping list_id -> ManifestEntry for
            source_file metadata. If None, source_file is derived from
            the custom_id only.

    Returns:
        Dict mapping list_id -> TaxonomyResult (OK or NOT_A_LIST).
        Failed responses are not included.
    """
    results: dict[str, TaxonomyResult] = {}

    for response in responses:
        # custom_id format: "taxonomy__<list_id>"
        list_id = response.custom_id.removeprefix("taxonomy__")

        source_file = ""
        if entries_by_id and list_id in entries_by_id:
            source_file = entries_by_id[list_id].file_path

        if response.error:
            logger.error("[%s] Taxonomy executor error: %s", list_id, response.error)
            progress.mark_taxonomy_done(list_id, "ERROR", error=response.error)
            continue

        try:
            result = _parse_taxonomy_response(response.content, source_file=source_file)
        except Exception as exc:
            logger.error("[%s] Taxonomy response parse error: %s", list_id, exc)
            progress.mark_taxonomy_done(list_id, "ERROR", error=str(exc))
            continue

        save_taxonomy(result, settings.taxonomy_dir, list_id)
        progress.mark_taxonomy_done(list_id, result.status, tokens=response.tokens)

        if result.status == "NOT_A_LIST":
            logger.info("[%s] Marked as NOT_A_LIST", list_id)
        else:
            cat_count = len(result.flat_categories())
            logger.info("[%s] Taxonomy OK: %d categories", list_id, cat_count)

        results[list_id] = result

    return results


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------

def _parse_taxonomy_response(raw_text: str, source_file: str) -> TaxonomyResult:
    """Parse the raw JSON response from the taxonomy model."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Taxonomy model returned invalid JSON: {exc}\nRaw: {raw_text[:500]}"
        ) from exc

    status = data.get("status", "OK")
    if status == "NOT_A_LIST":
        return TaxonomyResult(status="NOT_A_LIST", source_file=source_file)

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


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_taxonomy(result: TaxonomyResult, taxonomy_dir: Path, list_id: str) -> Path:
    """Save a TaxonomyResult to JSON in the taxonomy directory."""
    taxonomy_dir.mkdir(parents=True, exist_ok=True)
    out_path = taxonomy_dir / f"{list_id}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result.model_dump(), fh, indent=2, ensure_ascii=False)
    return out_path


def load_taxonomy(taxonomy_dir: Path, list_id: str) -> Optional[TaxonomyResult]:
    """Load a saved TaxonomyResult from disk, or None if not found."""
    path = taxonomy_dir / f"{list_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

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


def load_all_taxonomies(
    taxonomy_dir: Path,
) -> dict[str, TaxonomyResult]:
    """Load all saved taxonomy results; returns dict keyed by list_id."""
    results: dict[str, TaxonomyResult] = {}
    if not taxonomy_dir.exists():
        return results
    for p in sorted(taxonomy_dir.glob("*.json")):
        list_id = p.stem
        tax = load_taxonomy(taxonomy_dir, list_id)
        if tax is not None:
            results[list_id] = tax
    return results


# ---------------------------------------------------------------------------
# Convenience wrapper for individual sft-data extract-taxonomy command
# ---------------------------------------------------------------------------

def extract_taxonomy_for_all(
    entries: list[ManifestEntry],
    settings: SFTSettings,
    progress: ProgressTracker,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Optional[TaxonomyResult]]:
    """
    Run taxonomy extraction for all manifest entries using SyncExecutor.

    Convenience wrapper for the `sft-data extract-taxonomy` command.
    The full `sft-data run` orchestration uses prepare_taxonomy_requests /
    executor.execute / process_taxonomy_responses directly to support batch mode.
    """
    from winerank.sft.executor.sync import SyncExecutor

    entries_by_id = {e.list_id: e for e in entries}
    results: dict[str, Optional[TaxonomyResult]] = {}

    # Pre-populate results for already-completed entries
    for entry in entries:
        if not force and progress.is_taxonomy_done(entry.list_id):
            results[entry.list_id] = load_taxonomy(settings.taxonomy_dir, entry.list_id)

    if dry_run:
        for entry in entries:
            if entry.list_id not in results:
                logger.info("[%s] DRY RUN: would call %s for taxonomy",
                            entry.list_id, settings.taxonomy_model)
                results[entry.list_id] = None
        return results

    requests = prepare_taxonomy_requests(entries, settings, progress, force=force)
    if not requests:
        return results

    executor = SyncExecutor()
    responses = executor.execute(requests)
    processed = process_taxonomy_responses(
        responses, settings, progress, entries_by_id=entries_by_id
    )
    results.update(processed)

    # Mark failed requests as None
    for req in requests:
        list_id = req.custom_id.removeprefix("taxonomy__")
        if list_id not in results:
            results[list_id] = None

    return results
