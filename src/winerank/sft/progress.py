"""
Progress tracking and resumability for SFT pipeline.

Stores state in data/sft/progress.json so the pipeline can skip already-
completed work and resume after interruptions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


# Keys used in progress store
_KEY_TAXONOMY = "taxonomy"
_KEY_PARSE = "parse"
_KEY_JUDGE = "judge"


class ProgressTracker:
    """
    Track completion state for each pipeline step.

    The progress file has this structure:

    {
      "taxonomy": {
        "<list_id>": {"status": "OK"|"NOT_A_LIST"|"ERROR", "error": "...", "tokens": {...}}
      },
      "parse": {
        "<list_id>__<segment_index>": {"status": "OK"|"ERROR", ...}
      },
      "judge": {
        "<list_id>__<segment_index>": {"status": "OK"|"ERROR", ...}
      }
    }
    """

    def __init__(self, progress_file: Path) -> None:
        self._file = progress_file
        self._data: dict[str, Any] = {
            _KEY_TAXONOMY: {},
            _KEY_PARSE: {},
            _KEY_JUDGE: {},
        }
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._file.exists():
            try:
                with open(self._file, encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge keys -- keeps forward-compatible with new keys
                for k in (_KEY_TAXONOMY, _KEY_PARSE, _KEY_JUDGE):
                    if k in loaded:
                        self._data[k] = loaded[k]
            except (json.JSONDecodeError, OSError):
                # Corrupted file -- start fresh
                self._data = {
                    _KEY_TAXONOMY: {},
                    _KEY_PARSE: {},
                    _KEY_JUDGE: {},
                }

    def save(self) -> None:
        """Persist current state to disk."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def reset(self) -> None:
        """Clear all progress (used with --force flag)."""
        self._data = {
            _KEY_TAXONOMY: {},
            _KEY_PARSE: {},
            _KEY_JUDGE: {},
        }
        self.save()

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------

    def is_taxonomy_done(self, list_id: str) -> bool:
        entry = self._data[_KEY_TAXONOMY].get(list_id, {})
        return entry.get("status") in ("OK", "NOT_A_LIST")

    def mark_taxonomy_done(
        self,
        list_id: str,
        status: str,
        tokens: Optional[dict[str, int]] = None,
        error: Optional[str] = None,
    ) -> None:
        self._data[_KEY_TAXONOMY][list_id] = {
            "status": status,
            **({"tokens": tokens} if tokens else {}),
            **({"error": error} if error else {}),
        }
        self.save()

    def get_taxonomy_status(self, list_id: str) -> Optional[str]:
        return self._data[_KEY_TAXONOMY].get(list_id, {}).get("status")

    def get_not_a_list_ids(self) -> set[str]:
        return {
            k
            for k, v in self._data[_KEY_TAXONOMY].items()
            if v.get("status") == "NOT_A_LIST"
        }

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def _parse_key(self, list_id: str, segment_index: int) -> str:
        return f"{list_id}__{segment_index}"

    def is_parse_done(self, list_id: str, segment_index: int) -> bool:
        key = self._parse_key(list_id, segment_index)
        return self._data[_KEY_PARSE].get(key, {}).get("status") == "OK"

    def mark_parse_done(
        self,
        list_id: str,
        segment_index: int,
        tokens: Optional[dict[str, int]] = None,
        error: Optional[str] = None,
    ) -> None:
        key = self._parse_key(list_id, segment_index)
        status = "ERROR" if error else "OK"
        self._data[_KEY_PARSE][key] = {
            "status": status,
            **({"tokens": tokens} if tokens else {}),
            **({"error": error} if error else {}),
        }
        self.save()

    # ------------------------------------------------------------------
    # Judge
    # ------------------------------------------------------------------

    def is_judge_done(self, list_id: str, segment_index: int) -> bool:
        key = self._parse_key(list_id, segment_index)
        return self._data[_KEY_JUDGE].get(key, {}).get("status") == "OK"

    def mark_judge_done(
        self,
        list_id: str,
        segment_index: int,
        tokens: Optional[dict[str, int]] = None,
        error: Optional[str] = None,
    ) -> None:
        key = self._parse_key(list_id, segment_index)
        status = "ERROR" if error else "OK"
        self._data[_KEY_JUDGE][key] = {
            "status": status,
            **({"tokens": tokens} if tokens else {}),
            **({"error": error} if error else {}),
        }
        self.save()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary dict."""
        tax = self._data[_KEY_TAXONOMY]
        parse = self._data[_KEY_PARSE]
        judge = self._data[_KEY_JUDGE]

        return {
            "taxonomy": {
                "ok": sum(1 for v in tax.values() if v.get("status") == "OK"),
                "not_a_list": sum(1 for v in tax.values() if v.get("status") == "NOT_A_LIST"),
                "error": sum(1 for v in tax.values() if v.get("status") == "ERROR"),
                "total": len(tax),
            },
            "parse": {
                "ok": sum(1 for v in parse.values() if v.get("status") == "OK"),
                "error": sum(1 for v in parse.values() if v.get("status") == "ERROR"),
                "total": len(parse),
            },
            "judge": {
                "ok": sum(1 for v in judge.values() if v.get("status") == "OK"),
                "error": sum(1 for v in judge.values() if v.get("status") == "ERROR"),
                "total": len(judge),
            },
        }

    def total_tokens(self) -> dict[str, int]:
        """Sum up all tracked token usage."""
        totals = {"input": 0, "output": 0, "cached": 0}
        for section in (_KEY_TAXONOMY, _KEY_PARSE, _KEY_JUDGE):
            for entry in self._data[section].values():
                t = entry.get("tokens", {})
                totals["input"] += t.get("input", 0)
                totals["output"] += t.get("output", 0)
                totals["cached"] += t.get("cached", 0)
        return totals
