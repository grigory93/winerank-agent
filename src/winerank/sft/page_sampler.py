"""
Stratified random page/segment sampler for the SFT training data pipeline.

Selects a diverse, reproducible set of segments from validated wine lists,
proportionally weighted by list size but with per-list minimum and maximum caps.
"""
from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Optional

from winerank.sft.page_reader import extract_segments
from winerank.sft.progress import ProgressTracker
from winerank.sft.schemas import ManifestEntry, SampleManifestEntry, WineSegment

logger = logging.getLogger(__name__)


def _load_segments_for_list(
    entry: ManifestEntry,
    min_chars: int = 50,
) -> list[WineSegment]:
    """Extract and return all valid segments for a wine list entry."""
    file_path = Path(entry.file_path)
    if not file_path.exists():
        logger.warning("[%s] File not found: %s", entry.list_id, file_path)
        return []
    try:
        return extract_segments(file_path, list_id=entry.list_id, min_chars=min_chars)
    except Exception as e:
        logger.error("[%s] Failed to extract segments: %s", entry.list_id, e)
        return []


def sample_segments(
    entries: list[ManifestEntry],
    not_a_list_ids: set[str],
    num_samples: int,
    seed: int,
    min_per_list: int = 2,
    min_chars: int = 50,
) -> list[SampleManifestEntry]:
    """
    Stratified random sampling across all valid wine lists.

    Strategy:
    - Skip lists marked as NOT_A_LIST.
    - Collect all non-blank segments from each valid list.
    - Allocate samples proportionally to each list's segment count.
    - Enforce a minimum of ``min_per_list`` samples per list (if it has enough).
    - Enforce a per-list maximum of ceil(2 * avg_allocation) to prevent dominance.
    - Use a seeded RNG for reproducibility.

    Args:
        entries: All manifest entries.
        not_a_list_ids: Set of list IDs that failed wine list validation.
        num_samples: Target total sample count.
        seed: Random seed.
        min_per_list: Minimum samples per valid list.
        min_chars: Minimum characters per segment.

    Returns:
        List of SampleManifestEntry references.
    """
    rng = random.Random(seed)

    # Collect segments for valid lists only
    valid_lists: dict[str, list[WineSegment]] = {}
    for entry in entries:
        if entry.list_id in not_a_list_ids:
            logger.info("[%s] Skipping (NOT_A_LIST)", entry.list_id)
            continue
        segs = _load_segments_for_list(entry, min_chars=min_chars)
        if segs:
            valid_lists[entry.list_id] = segs
        else:
            logger.warning("[%s] No valid segments found", entry.list_id)

    if not valid_lists:
        logger.error("No valid wine lists found for sampling")
        return []

    n_lists = len(valid_lists)
    avg_allocation = num_samples / n_lists

    # Compute per-list max cap (prevent any single list from dominating)
    max_per_list = max(min_per_list, math.ceil(avg_allocation * 2))

    # First pass: proportional allocation
    total_segs = sum(len(segs) for segs in valid_lists.values())
    raw_alloc: dict[str, int] = {}
    for list_id, segs in valid_lists.items():
        proportion = len(segs) / total_segs
        raw_alloc[list_id] = min(
            max(min_per_list, round(proportion * num_samples)),
            max_per_list,
            len(segs),
        )

    # Adjust to hit target total
    current_total = sum(raw_alloc.values())
    if current_total != num_samples:
        diff = num_samples - current_total
        # Distribute remaining quota to lists that have room to grow
        sorted_ids = sorted(
            raw_alloc.keys(),
            key=lambda k: len(valid_lists[k]) - raw_alloc[k],
            reverse=True,
        )
        for list_id in sorted_ids:
            if diff == 0:
                break
            available = min(max_per_list, len(valid_lists[list_id])) - raw_alloc[list_id]
            add = max(0, min(available, diff))
            raw_alloc[list_id] += add
            diff -= add
        # If still over/under, trim/pad the biggest list
        if diff != 0:
            biggest = max(raw_alloc, key=lambda k: raw_alloc[k])
            raw_alloc[biggest] = max(min_per_list, raw_alloc[biggest] + diff)

    # Sample from each list
    samples: list[SampleManifestEntry] = []
    for list_id, segs in valid_lists.items():
        alloc = raw_alloc.get(list_id, min_per_list)
        chosen = rng.sample(segs, min(alloc, len(segs)))
        for seg in chosen:
            samples.append(
                SampleManifestEntry(
                    list_id=seg.list_id,
                    segment_index=seg.segment_index,
                    source_file=seg.source_file,
                    file_type=seg.file_type,
                    char_count=seg.char_count,
                )
            )

    # Shuffle final list so order isn't grouped by wine list
    rng.shuffle(samples)
    logger.info(
        "Sampled %d segments from %d valid lists (target: %d)",
        len(samples),
        n_lists,
        num_samples,
    )
    return samples


def save_samples(samples: list[SampleManifestEntry], samples_file: Path) -> None:
    """Persist sample list to JSON."""
    samples_file.parent.mkdir(parents=True, exist_ok=True)
    with open(samples_file, "w", encoding="utf-8") as f:
        json.dump([s.model_dump() for s in samples], f, indent=2)


def load_samples(samples_file: Path) -> list[SampleManifestEntry]:
    """Load sample list from JSON."""
    if not samples_file.exists():
        raise FileNotFoundError(
            f"Samples file not found: {samples_file}. "
            "Run 'winerank sft sample' first."
        )
    with open(samples_file, encoding="utf-8") as f:
        data = json.load(f)
    return [SampleManifestEntry(**item) for item in data]
