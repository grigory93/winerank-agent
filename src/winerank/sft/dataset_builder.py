"""
Dataset builder: assemble SFT-ready JSONL training files.

Outputs OpenAI chat-completion JSONL format (compatible with OpenAI Fine-Tuning
API, HuggingFace TRL SFTTrainer, Axolotl, LLaMA-Factory, Unsloth).

Each line:
  {"messages": [
    {"role": "system", "content": "..."},
    {"role": "user",   "content": "VALID CATEGORIES:\n...\n\nRAW TEXT TO PARSE:\n..."},
    {"role": "assistant", "content": "{\"wines\": [...]}"}
  ]}

A metadata.json is written alongside for full provenance.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from winerank.sft.config import SFTSettings
from winerank.sft.judge_reviewer import load_all_judge_results
from winerank.sft.prompts import WINE_PARSING_SYSTEM_PROMPT, WINE_PARSING_USER_PROMPT
from winerank.sft.progress import ProgressTracker
from winerank.sft.schemas import DatasetMetadata, JudgeResult, PageParseResult, TrainingSample
from winerank.sft.wine_parser import load_all_parse_results

logger = logging.getLogger(__name__)


def _build_training_sample(
    parse_result: PageParseResult,
    judge_result: Optional[JudgeResult] = None,
) -> TrainingSample:
    """Convert a ParseResult into a JSONL training sample."""
    user_content = WINE_PARSING_USER_PROMPT.format(
        taxonomy_text=parse_result.taxonomy_text,
        segment_text=parse_result.segment_text,
    )
    assistant_content = json.dumps(
        {"wines": [w.model_dump(exclude_none=True) for w in parse_result.wines]},
        ensure_ascii=False,
    )

    meta: dict = {
        "segment_id": parse_result.segment_id,
        "list_id": parse_result.list_id,
        "source_file": parse_result.source_file,
        "model_used": parse_result.model_used,
    }
    if judge_result:
        meta["judge_score"] = judge_result.score
        meta["judge_recommendation"] = judge_result.recommendation

    return TrainingSample(
        messages=[
            {"role": "system", "content": WINE_PARSING_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        metadata=meta,
    )


def build_dataset(
    settings: SFTSettings,
    progress: ProgressTracker,
    min_judge_score: Optional[float] = None,
) -> Path:
    """
    Assemble the final JSONL training dataset.

    Reads all parsed results from data/sft/parsed/ and judge results from
    data/sft/judged/ (if present), applies filtering, and writes to
    data/sft/dataset/wine_parse_train.jsonl alongside metadata.json.

    Args:
        settings: SFT settings.
        progress: ProgressTracker (for cost/token stats).
        min_judge_score: Minimum judge score to include a sample.
                         None or 0.0 = include all.

    Returns:
        Path to the output JSONL file.
    """
    settings.ensure_dirs()

    threshold = min_judge_score if min_judge_score and min_judge_score > 0.0 else None

    parse_results = load_all_parse_results(settings.parsed_dir)
    judge_map = load_all_judge_results(settings.judged_dir)

    if not parse_results:
        logger.warning("No parsed results found in %s", settings.parsed_dir)

    samples: list[TrainingSample] = []
    judge_filtered = 0
    not_a_list_count = 0  # tracked separately during taxonomy phase
    corrected_count = 0

    for pr in parse_results:
        # Skip segments with parse errors
        if pr.parse_error:
            logger.debug("[%s] Skipping (parse error)", pr.segment_id)
            continue
        # Skip if no wines extracted
        if not pr.wines:
            logger.debug("[%s] Skipping (no wines extracted)", pr.segment_id)
            continue

        judge = judge_map.get(pr.segment_id)

        if threshold is not None and judge is not None:
            if judge.score < threshold:
                judge_filtered += 1
                logger.debug(
                    "[%s] Filtered by judge score %.2f < %.2f",
                    pr.segment_id, judge.score, threshold,
                )
                continue

        if pr.correction_round > 0:
            corrected_count += 1

        samples.append(_build_training_sample(pr, judge))

    # Collect stats for metadata
    token_totals = progress.total_tokens()
    prog_summary = progress.summary()

    # Count unique lists used in final dataset
    lists_used = len({s.metadata["list_id"] for s in samples if s.metadata})

    correction_rounds = prog_summary.get("correction", {}).get("rounds", [])

    meta = DatasetMetadata(
        generated_at=datetime.now(timezone.utc).isoformat(),
        taxonomy_model=settings.taxonomy_model,
        teacher_model=settings.teacher_model,
        judge_model=settings.judge_model if judge_map else None,
        training_data_mode=settings.training_data_mode,
        num_samples_target=settings.num_samples,
        num_samples_actual=len(samples),
        num_lists_used=lists_used,
        not_a_list_count=prog_summary["taxonomy"].get("not_a_list", 0),
        judge_filtered_count=judge_filtered,
        seed=settings.seed,
        min_judge_score=threshold or 0.0,
        total_input_tokens=token_totals.get("input", 0),
        total_output_tokens=token_totals.get("output", 0),
        total_cached_tokens=token_totals.get("cached", 0),
        correction_rounds_run=len(correction_rounds),
        corrected_samples_count=corrected_count,
    )

    # Write JSONL
    jsonl_path = settings.dataset_dir / "wine_parse_train.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for sample in samples:
            line = {"messages": sample.messages}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    # Write metadata
    meta_path = settings.dataset_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta.model_dump(), f, indent=2, ensure_ascii=False)

    logger.info(
        "Dataset built: %d samples, %d judge-filtered, written to %s",
        len(samples), judge_filtered, jsonl_path,
    )
    return jsonl_path


def load_dataset_metadata(dataset_dir: Path) -> Optional[DatasetMetadata]:
    """Load dataset metadata from metadata.json, or None if not found."""
    meta_path = dataset_dir / "metadata.json"
    if not meta_path.exists():
        return None
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    return DatasetMetadata(**data)
