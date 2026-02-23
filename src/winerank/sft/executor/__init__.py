"""LLM executor abstraction for the SFT pipeline.

Provides a clean separation between request building (pure data, done in
pipeline modules) and request execution (sync or batch, done here).

Usage:
    from winerank.sft.executor import LLMRequest, LLMResponse, create_executor

    executor = create_executor(batch_mode=False)
    responses = executor.execute(requests)
"""
from __future__ import annotations

from pathlib import Path

from winerank.sft.executor.base import LLMExecutor
from winerank.sft.executor.types import LLMRequest, LLMResponse

__all__ = [
    "LLMExecutor",
    "LLMRequest",
    "LLMResponse",
    "create_executor",
]


def create_executor(
    batch_mode: bool = False,
    data_dir: Path | None = None,
    batch_timeout: int = 7200,
) -> LLMExecutor:
    """
    Factory: return the appropriate executor for the current run mode.

    Args:
        batch_mode: When True, use provider-native batch APIs (50% cost
            reduction, async, up to 24h turnaround). When False (default),
            use synchronous litellm calls -- suitable for development,
            testing, and small --limit runs.
        data_dir: Base SFT data directory. Required for BatchExecutor (used
            to persist pending batch IDs for resume on crash).
        batch_timeout: Maximum seconds to wait for batch completion (default
            7200 = 2 hours).

    Returns:
        LLMExecutor instance.
    """
    if batch_mode:
        from winerank.sft.executor.batch import BatchExecutor
        return BatchExecutor(data_dir=data_dir, timeout=batch_timeout)

    from winerank.sft.executor.sync import SyncExecutor
    return SyncExecutor()
