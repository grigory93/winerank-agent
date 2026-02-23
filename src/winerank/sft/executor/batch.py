"""Batch LLM executor using provider-native batch APIs.

Supports OpenAI Batch API and Anthropic Message Batches API.
Both APIs offer 50% cost reduction vs synchronous calls.
Prompt caching stacks with the batch discount.

Batch lifecycle
---------------
1. prepare() -- split requests by provider, serialize to provider format
2. submit() -- upload / create batch job, persist batch ID to pending_batch.json
3. poll()   -- wait for completion, exponential backoff
4. collect() -- download results, map back to LLMResponse by custom_id
5. cleanup() -- remove pending_batch.json entry on success

Crash recovery
--------------
If the process dies during polling, pending_batch.json retains the batch ID.
On next invocation the BatchExecutor finds the existing batch ID and resumes
polling from step 3 instead of re-submitting (which would waste money).
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, cast

try:
    import openai  # type: ignore[import-untyped]
except ImportError:
    openai = None  # type: ignore[assignment]

try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:
    anthropic = None  # type: ignore[assignment]

from winerank.sft.executor.base import LLMExecutor
from winerank.sft.executor.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


def _strip_markdown_fence(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences that some LLMs wrap around JSON."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text

_PENDING_FILE = "pending_batch.json"
_POLL_INITIAL = 30          # seconds before first status check
_POLL_MAX = 300             # cap backoff at 5 minutes
_POLL_MULTIPLIER = 1.5      # backoff growth factor
_CUSTOM_ID_MAX_LEN = 64     # Anthropic and OpenAI batch APIs both enforce this limit


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or "anthropic" in model.lower()


# ---------------------------------------------------------------------------
# custom_id normalization (Anthropic and OpenAI both cap at 64 chars)
# ---------------------------------------------------------------------------

def _normalize_custom_ids(
    requests: list[LLMRequest],
) -> tuple[list[LLMRequest], dict[str, str]]:
    """
    Replace custom_ids longer than 64 characters with short sequential IDs.

    Both Anthropic and OpenAI batch APIs reject requests where custom_id
    exceeds 64 characters. Pipeline IDs like "parse__the-modern-wine-list__123"
    can easily exceed this when list filenames are long.

    Returns:
        (normalized_requests, short_to_original): normalized_requests has
        short IDs ("b0", "b1", ...); short_to_original maps each short ID
        back to the original so callers can restore after collecting results.
        If no ID exceeds 64 chars, returns (requests, {}) unchanged.
    """
    if all(len(r.custom_id) <= _CUSTOM_ID_MAX_LEN for r in requests):
        return requests, {}

    short_to_original: dict[str, str] = {}
    normalized: list[LLMRequest] = []
    for i, req in enumerate(requests):
        short_id = f"b{i}"
        short_to_original[short_id] = req.custom_id
        normalized.append(replace(req, custom_id=short_id))

    logger.debug(
        "Normalized %d custom_ids to short form (longest original: %d chars)",
        len(normalized),
        max(len(r.custom_id) for r in requests),
    )
    return normalized, short_to_original


def _restore_custom_ids(
    responses: list[LLMResponse],
    short_to_original: dict[str, str],
) -> list[LLMResponse]:
    """
    Restore original custom_ids on responses after batch collection.

    Inverse of _normalize_custom_ids. If short_to_original is empty
    (no normalization was needed), returns responses unchanged.
    """
    if not short_to_original:
        return responses
    return [
        replace(resp, custom_id=short_to_original.get(resp.custom_id, resp.custom_id))
        for resp in responses
    ]


# ---------------------------------------------------------------------------
# OpenAI batch helpers
# ---------------------------------------------------------------------------

def _build_openai_batch_line(req: LLMRequest) -> dict:
    """Build a single JSONL line for the OpenAI Batch API."""
    body: dict = {
        "model": req.model,
        "messages": req.messages,
        "max_completion_tokens": req.max_tokens,
        "temperature": req.temperature,
    }
    if req.response_format is not None:
        body["response_format"] = req.response_format
    return {
        "custom_id": req.custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": body,
    }


def _submit_openai_batch(requests: list[LLMRequest], api_key: str | None = None) -> str:
    """Upload JSONL file and create OpenAI batch job. Returns batch_id."""
    if openai is None:
        raise RuntimeError("openai SDK is not installed. Run: pip install openai>=1.50")
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    lines = [json.dumps(_build_openai_batch_line(r)) for r in requests]
    jsonl_bytes = "\n".join(lines).encode()

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp.write(jsonl_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as fh:
            file_obj = client.files.create(file=fh, purpose="batch")
        batch = client.batches.create(
            input_file_id=file_obj.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        logger.info("OpenAI batch submitted: %s (%d requests)", batch.id, len(requests))
        return batch.id
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _poll_openai_batch(batch_id: str, timeout: int, api_key: str | None = None) -> Any:
    """Poll until the OpenAI batch completes. Returns the finished batch object."""
    if openai is None:
        raise RuntimeError("openai SDK is not installed. Run: pip install openai>=1.50")
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
    deadline = time.monotonic() + timeout
    interval = _POLL_INITIAL

    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        logger.info("OpenAI batch %s status: %s", batch_id, status)

        if status == "completed":
            return batch
        if status in ("failed", "expired", "cancelled"):
            raise RuntimeError(f"OpenAI batch {batch_id} ended with status: {status}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"OpenAI batch {batch_id} did not complete within {timeout}s")

        time.sleep(interval)
        interval = min(interval * _POLL_MULTIPLIER, _POLL_MAX)


def _collect_openai_results(batch: Any, requests: list[LLMRequest], api_key: str | None = None) -> list[LLMResponse]:
    """Download batch output file and build LLMResponse list."""
    if openai is None:
        raise RuntimeError("openai SDK is not installed. Run: pip install openai>=1.50")
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    req_map = {r.custom_id: r for r in requests}
    responses: dict[str, LLMResponse] = {}

    if not batch.output_file_id:
        # Batch completed but produced no output (all requests failed).
        error_msg = "Batch completed with no output file"
        error_file_id = getattr(batch, "error_file_id", None)
        if error_file_id:
            try:
                err_raw = client.files.content(error_file_id).content
                error_msg += f"; errors: {err_raw.decode()[:500]}"
            except Exception:
                pass
        logger.error(
            "OpenAI batch %s: %s. Delete data/sft/pending_batch.json and re-run to submit a new batch.",
            batch.id,
            error_msg,
        )
        return [
            LLMResponse(
                custom_id=r.custom_id,
                content="",
                tokens={"input": 0, "output": 0, "cached": 0},
                error=error_msg,
            )
            for r in requests
        ]

    raw = client.files.content(batch.output_file_id).content
    for line in raw.decode().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        cid = item["custom_id"]
        result = item.get("response", {})
        body = result.get("body", {})
        choices = body.get("choices", [])
        usage = body.get("usage", {})
        error = item.get("error")

        if error or not choices:
            responses[cid] = LLMResponse(
                custom_id=cid,
                content="",
                tokens={"input": 0, "output": 0, "cached": 0},
                error=str(error or "no choices returned"),
            )
        else:
            content = choices[0].get("message", {}).get("content", "")
            orig_req = req_map.get(cid)
            if orig_req and orig_req.response_format == {"type": "json_object"}:
                content = _strip_markdown_fence(content)
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            details = usage.get("prompt_tokens_details", {}) or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
            responses[cid] = LLMResponse(
                custom_id=cid,
                content=content,
                tokens={"input": pt, "output": ct, "cached": cached},
            )

    # Fill in errors for any requests not in the output file
    for cid in req_map:
        if cid not in responses:
            responses[cid] = LLMResponse(
                custom_id=cid,
                content="",
                tokens={"input": 0, "output": 0, "cached": 0},
                error="Request not found in batch output",
            )

    return [responses[r.custom_id] for r in requests]


# ---------------------------------------------------------------------------
# Anthropic batch helpers
# ---------------------------------------------------------------------------

def _inject_anthropic_cache_control(req: LLMRequest) -> list[dict]:
    """
    Return a copy of messages with cache_control blocks injected per
    req.cache_control_injection_points.

    Injection point format: {'location': 'system'} or
    {'location': 'message_content', 'message_index': N, 'content_index': M}

    This mirrors what litellm does for synchronous calls so that the batch
    API also benefits from prompt caching (discounts stack).
    """
    import copy
    messages = copy.deepcopy(req.messages)

    if not req.cache_control_injection_points:
        return messages

    for point in req.cache_control_injection_points:
        location = point.get("location")
        if location == "system":
            # Find the system message and inject at the end of its content
            for msg in messages:
                if msg.get("role") == "system":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        msg["content"] = [
                            {"type": "text", "text": content,
                             "cache_control": {"type": "ephemeral"}}
                        ]
                    elif isinstance(content, list) and content:
                        content[-1]["cache_control"] = {"type": "ephemeral"}
        elif location == "message_content":
            msg_idx = point.get("message_index", 0)
            cnt_idx = point.get("content_index", 0)
            if msg_idx < len(messages):
                msg = messages[msg_idx]
                content = msg.get("content", [])
                if isinstance(content, list) and cnt_idx < len(content):
                    content[cnt_idx]["cache_control"] = {"type": "ephemeral"}

    return messages


def _build_anthropic_batch_request(req: LLMRequest) -> dict:
    """Build a single request object for the Anthropic Message Batches API."""
    messages = _inject_anthropic_cache_control(req)

    # Anthropic uses 'system' as a top-level field, not a message role
    system_content: str | list | None = None
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            user_messages.append(msg)

    params: dict = {
        "model": req.model,
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "messages": user_messages,
    }
    if system_content is not None:
        params["system"] = system_content

    return {"custom_id": req.custom_id, "params": params}


def _submit_anthropic_batch(requests: list[LLMRequest], api_key: str | None = None) -> str:
    """Submit an Anthropic Message Batch. Returns the batch ID."""
    if anthropic is None:
        raise RuntimeError("anthropic SDK is not installed. Run: pip install anthropic>=0.40")
    from anthropic.types.messages.batch_create_params import Request as AnthropicBatchRequest

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    batch_requests = [_build_anthropic_batch_request(r) for r in requests]
    batch = client.messages.batches.create(
        requests=cast(Iterable[AnthropicBatchRequest], batch_requests)
    )
    logger.info("Anthropic batch submitted: %s (%d requests)", batch.id, len(requests))
    return batch.id


def _poll_anthropic_batch(batch_id: str, timeout: int, api_key: str | None = None) -> Any:
    """Poll until the Anthropic batch ends. Returns the finished batch object."""
    if anthropic is None:
        raise RuntimeError("anthropic SDK is not installed. Run: pip install anthropic>=0.40")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    deadline = time.monotonic() + timeout
    interval = _POLL_INITIAL

    while True:
        batch = client.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        counts = batch.request_counts
        logger.info(
            "Anthropic batch %s: %s (succeeded=%d errored=%d processing=%d)",
            batch_id, status,
            getattr(counts, "succeeded", 0),
            getattr(counts, "errored", 0),
            getattr(counts, "processing", 0),
        )

        if status == "ended":
            return batch
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Anthropic batch {batch_id} did not complete within {timeout}s")

        time.sleep(interval)
        interval = min(interval * _POLL_MULTIPLIER, _POLL_MAX)


def _collect_anthropic_results(
    batch_id: str, requests: list[LLMRequest], api_key: str | None = None
) -> list[LLMResponse]:
    """Stream Anthropic batch results and build LLMResponse list."""
    if anthropic is None:
        raise RuntimeError("anthropic SDK is not installed. Run: pip install anthropic>=0.40")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    req_map = {r.custom_id: r for r in requests}
    responses: dict[str, LLMResponse] = {}

    for result in client.messages.batches.results(batch_id):
        cid = result.custom_id
        result_type = result.result.type if hasattr(result.result, "type") else str(result.result)

        if result_type == "succeeded":
            msg = getattr(result.result, "message", None)
            content = ""
            if msg is not None and hasattr(msg, "content") and msg.content:
                block = msg.content[0]
                content = getattr(block, "text", "") if hasattr(block, "text") else str(block)
            orig_req = req_map.get(cid)
            if orig_req and orig_req.response_format == {"type": "json_object"}:
                content = _strip_markdown_fence(content)
            usage = getattr(msg, "usage", None)
            inp = getattr(usage, "input_tokens", 0) if usage else 0
            out = getattr(usage, "output_tokens", 0) if usage else 0
            cached = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
            responses[cid] = LLMResponse(
                custom_id=cid,
                content=content,
                tokens={"input": inp, "output": out, "cached": cached},
            )
        else:
            error_detail = str(getattr(result.result, "error", result_type))
            responses[cid] = LLMResponse(
                custom_id=cid,
                content="",
                tokens={"input": 0, "output": 0, "cached": 0},
                error=error_detail,
            )

    # Fill missing
    for cid in req_map:
        if cid not in responses:
            responses[cid] = LLMResponse(
                custom_id=cid,
                content="",
                tokens={"input": 0, "output": 0, "cached": 0},
                error="Request not found in batch results",
            )

    return [responses[r.custom_id] for r in requests]


# ---------------------------------------------------------------------------
# BatchExecutor
# ---------------------------------------------------------------------------

class BatchExecutor(LLMExecutor):
    """
    Executes LLM requests via provider-native batch APIs.

    - OpenAI models: uses openai.batches (JSONL file upload, 50% discount)
    - Anthropic models: uses anthropic.messages.batches (50% discount)

    Both APIs support prompt caching: discounts stack. For Anthropic, the
    executor injects cache_control blocks from LLMRequest.cache_control_injection_points
    directly into the batch payload.

    If the process crashes during polling, the batch ID is preserved in
    data/sft/pending_batch.json so the next run resumes polling instead of
    resubmitting.

    NOTE: Batch execution is asynchronous (up to 24 hours). Use SyncExecutor
    for interactive development or when you need immediate results.
    """

    def __init__(self, data_dir: Path | None = None, timeout: int = 7200) -> None:
        self._data_dir = data_dir
        self._timeout = timeout
        self._pending_file = (data_dir / _PENDING_FILE) if data_dir else None

    # ------------------------------------------------------------------
    # Pending batch ID persistence
    # ------------------------------------------------------------------

    def _load_pending(self) -> dict:
        if self._pending_file and self._pending_file.exists():
            try:
                return json.loads(self._pending_file.read_text())
            except Exception:
                return {}
        return {}

    def _save_pending(self, key: str, batch_id: str, provider: str) -> None:
        if not self._pending_file:
            return
        self._pending_file.parent.mkdir(parents=True, exist_ok=True)
        pending = self._load_pending()
        pending[key] = {"batch_id": batch_id, "provider": provider}
        self._pending_file.write_text(json.dumps(pending, indent=2))

    def _clear_pending(self, key: str) -> None:
        if not self._pending_file or not self._pending_file.exists():
            return
        pending = self._load_pending()
        pending.pop(key, None)
        self._pending_file.write_text(json.dumps(pending, indent=2))

    # ------------------------------------------------------------------
    # Per-provider execution
    # ------------------------------------------------------------------

    def _execute_openai(
        self, requests: list[LLMRequest], batch_key: str
    ) -> list[LLMResponse]:
        # Normalize before touching the API; restore originals on the way out.
        requests, short_to_original = _normalize_custom_ids(requests)

        pending = self._load_pending()
        existing = pending.get(batch_key)

        if existing and existing.get("provider") == "openai":
            batch_id = existing["batch_id"]
            logger.info("Resuming OpenAI batch %s", batch_id)
        else:
            batch_id = _submit_openai_batch(requests)
            self._save_pending(batch_key, batch_id, "openai")

        batch = _poll_openai_batch(batch_id, timeout=self._timeout)
        results = _collect_openai_results(batch, requests)
        self._clear_pending(batch_key)
        return _restore_custom_ids(results, short_to_original)

    def _execute_anthropic(
        self, requests: list[LLMRequest], batch_key: str
    ) -> list[LLMResponse]:
        # Normalize before touching the API; restore originals on the way out.
        requests, short_to_original = _normalize_custom_ids(requests)

        pending = self._load_pending()
        existing = pending.get(batch_key)

        if existing and existing.get("provider") == "anthropic":
            batch_id = existing["batch_id"]
            logger.info("Resuming Anthropic batch %s", batch_id)
        else:
            batch_id = _submit_anthropic_batch(requests)
            self._save_pending(batch_key, batch_id, "anthropic")

        _poll_anthropic_batch(batch_id, timeout=self._timeout)
        results = _collect_anthropic_results(batch_id, requests)
        self._clear_pending(batch_key)
        return _restore_custom_ids(results, short_to_original)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self, requests: list[LLMRequest]) -> list[LLMResponse]:
        """
        Execute requests in batch mode.

        Requests are grouped by provider (Anthropic vs OpenAI). Each group
        is submitted as a separate batch since providers do not mix. Results
        are merged back in original request order.
        """
        if not requests:
            return []

        # Partition by provider
        anthropic_reqs = [r for r in requests if _is_anthropic_model(r.model)]
        openai_reqs = [r for r in requests if not _is_anthropic_model(r.model)]

        results_by_id: dict[str, LLMResponse] = {}

        if anthropic_reqs:
            # Use a stable key derived from the first custom_id prefix and count
            batch_key = f"anthropic_{anthropic_reqs[0].custom_id}_{len(anthropic_reqs)}"
            for resp in self._execute_anthropic(anthropic_reqs, batch_key):
                results_by_id[resp.custom_id] = resp

        if openai_reqs:
            batch_key = f"openai_{openai_reqs[0].custom_id}_{len(openai_reqs)}"
            for resp in self._execute_openai(openai_reqs, batch_key):
                results_by_id[resp.custom_id] = resp

        # Return in original order
        return [results_by_id[r.custom_id] for r in requests]
