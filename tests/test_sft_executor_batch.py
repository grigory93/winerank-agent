"""Tests for BatchExecutor -- OpenAI and Anthropic batch paths with mocked SDKs."""
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from winerank.sft.executor.batch import (
    BatchExecutor,
    _build_openai_batch_line,
    _inject_anthropic_cache_control,
    _is_anthropic_model,
    _normalize_custom_ids,
    _restore_custom_ids,
)
from winerank.sft.executor.types import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_openai_req(custom_id="r1", model="gpt-4o-mini"):
    return LLMRequest(
        custom_id=custom_id,
        model=model,
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        max_tokens=100,
        response_format={"type": "json_object"},
    )


def _make_anthropic_req(custom_id="a1", model="claude-opus-4-5"):
    return LLMRequest(
        custom_id=custom_id,
        model=model,
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        max_tokens=100,
        response_format={"type": "json_object"},
        cache_control_injection_points=[{"location": "system"}],
    )


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def test_is_anthropic_model_detects_claude():
    assert _is_anthropic_model("claude-opus-4-5")
    assert _is_anthropic_model("claude-haiku-3-5")
    assert not _is_anthropic_model("gpt-4o")
    assert not _is_anthropic_model("gpt-4o-mini")


# ---------------------------------------------------------------------------
# custom_id normalization (64-char provider limit)
# ---------------------------------------------------------------------------

def test_normalize_custom_ids_short_ids_unchanged():
    """Short IDs (<=64 chars) should pass through unchanged."""
    reqs = [_make_openai_req(f"r{i}") for i in range(3)]
    normalized, mapping = _normalize_custom_ids(reqs)
    assert mapping == {}
    assert normalized is reqs


def test_normalize_custom_ids_long_id_replaced():
    """A single long ID should trigger normalization for all requests."""
    long_id = "parse__" + "x" * 60 + "__0"  # 69 chars
    reqs = [
        _make_openai_req("short"),
        _make_openai_req(long_id),
    ]
    normalized, mapping = _normalize_custom_ids(reqs)
    assert len(mapping) == 2
    assert all(len(r.custom_id) <= 64 for r in normalized)
    assert normalized[0].custom_id == "b0"
    assert normalized[1].custom_id == "b1"
    assert mapping["b0"] == "short"
    assert mapping["b1"] == long_id


def test_normalize_custom_ids_exactly_64_chars_unchanged():
    """custom_id of exactly 64 chars should NOT be normalized."""
    exact = "x" * 64
    reqs = [_make_openai_req(exact)]
    normalized, mapping = _normalize_custom_ids(reqs)
    assert mapping == {}
    assert normalized is reqs


def test_restore_custom_ids_reverses_normalization():
    """Restored responses should carry original custom_ids."""
    long_id = "parse__" + "a" * 60 + "__5"
    reqs = [_make_openai_req("ok"), _make_openai_req(long_id)]
    normalized, mapping = _normalize_custom_ids(reqs)

    # Simulate responses using the short custom_ids
    fake_responses = [
        LLMResponse(custom_id="b0", content="resp0"),
        LLMResponse(custom_id="b1", content="resp1"),
    ]
    restored = _restore_custom_ids(fake_responses, mapping)
    assert restored[0].custom_id == "ok"
    assert restored[1].custom_id == long_id
    # Content is unchanged
    assert restored[0].content == "resp0"
    assert restored[1].content == "resp1"


def test_restore_custom_ids_empty_mapping_noop():
    resps = [LLMResponse(custom_id="r1", content="c")]
    assert _restore_custom_ids(resps, {}) is resps


def test_execute_anthropic_normalizes_long_custom_ids(tmp_path):
    """BatchExecutor._execute_anthropic must shorten IDs before submitting
    and return responses with original IDs restored."""
    long_id = "parse__" + "v" * 60 + "__0"  # 69 chars > 64
    req = _make_anthropic_req(long_id)

    mock_client = MagicMock()
    mock_batch = MagicMock()
    mock_batch.id = "msgbatch_norm"
    mock_client.messages.batches.create.return_value = mock_batch

    poll_result = MagicMock()
    poll_result.processing_status = "ended"
    poll_result.request_counts.succeeded = 1
    poll_result.request_counts.errored = 0
    poll_result.request_counts.processing = 0
    mock_client.messages.batches.retrieve.return_value = poll_result

    # Anthropic returns result with the SHORT custom_id ("b0")
    result_item = MagicMock()
    result_item.custom_id = "b0"
    result_item.result.type = "succeeded"
    msg = MagicMock()
    msg.content = [MagicMock(text="wine json")]
    msg.usage = MagicMock(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
    result_item.result.message = msg
    mock_client.messages.batches.results.return_value = [result_item]

    with patch("winerank.sft.executor.batch.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        executor = BatchExecutor(data_dir=tmp_path, timeout=60)
        responses = executor._execute_anthropic([req], "test_norm_key")

    # Submitted request must have had a short custom_id (b0)
    submitted = mock_client.messages.batches.create.call_args[1]["requests"]
    assert submitted[0]["custom_id"] == "b0"

    # Returned response must have the original long custom_id restored
    assert len(responses) == 1
    assert responses[0].custom_id == long_id


# ---------------------------------------------------------------------------
# OpenAI batch line builder
# ---------------------------------------------------------------------------

def test_build_openai_batch_line_structure():
    req = _make_openai_req()
    line = _build_openai_batch_line(req)
    assert line["custom_id"] == "r1"
    assert line["method"] == "POST"
    assert line["url"] == "/v1/chat/completions"
    assert "body" in line
    assert line["body"]["model"] == "gpt-4o-mini"
    assert line["body"]["messages"] == req.messages
    assert line["body"]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Anthropic cache control injection
# ---------------------------------------------------------------------------

def test_inject_anthropic_cache_system_string():
    req = LLMRequest(
        custom_id="r1",
        model="claude-opus-4-5",
        messages=[
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "user text"},
        ],
        cache_control_injection_points=[{"location": "system"}],
    )
    messages = _inject_anthropic_cache_control(req)
    sys_msg = next(m for m in messages if m["role"] == "system")
    # String content should be converted to a list block with cache_control
    assert isinstance(sys_msg["content"], list)
    assert sys_msg["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_inject_anthropic_cache_no_injection_points():
    req = LLMRequest(
        custom_id="r1",
        model="claude-opus-4-5",
        messages=[{"role": "user", "content": "hi"}],
        cache_control_injection_points=None,
    )
    messages = _inject_anthropic_cache_control(req)
    assert messages == req.messages


# ---------------------------------------------------------------------------
# Pending batch persistence
# ---------------------------------------------------------------------------

def test_batch_executor_saves_pending_batch_id(tmp_path):
    executor = BatchExecutor(data_dir=tmp_path)
    executor._save_pending("test_key", "batch_123", "openai")
    pending = executor._load_pending()
    assert pending["test_key"]["batch_id"] == "batch_123"
    assert pending["test_key"]["provider"] == "openai"


def test_batch_executor_clears_pending_after_completion(tmp_path):
    executor = BatchExecutor(data_dir=tmp_path)
    executor._save_pending("test_key", "batch_123", "openai")
    executor._clear_pending("test_key")
    pending = executor._load_pending()
    assert "test_key" not in pending


def test_batch_executor_load_pending_returns_empty_when_no_file(tmp_path):
    executor = BatchExecutor(data_dir=tmp_path)
    assert executor._load_pending() == {}


# ---------------------------------------------------------------------------
# OpenAI batch full path (mocked)
# ---------------------------------------------------------------------------

def _make_openai_output_line(custom_id, content):
    return json.dumps({
        "custom_id": custom_id,
        "response": {
            "body": {
                "choices": [{"message": {"content": content}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            }
        },
    })


def test_openai_batch_submit_poll_collect(tmp_path):
    requests = [_make_openai_req(f"r{i}") for i in range(3)]

    # Mock openai client
    mock_client = MagicMock()
    mock_file = MagicMock()
    mock_file.id = "file-abc"
    mock_client.files.create.return_value = mock_file

    mock_batch = MagicMock()
    mock_batch.id = "batch_xyz"
    mock_batch.status = "completed"
    mock_batch.output_file_id = "file-out"
    mock_client.batches.create.return_value = mock_batch
    mock_client.batches.retrieve.return_value = mock_batch

    output_lines = "\n".join(_make_openai_output_line(f"r{i}", f"content{i}") for i in range(3))
    mock_client.files.content.return_value.content = output_lines.encode()

    with patch("winerank.sft.executor.batch.openai") as mock_openai:
        mock_openai.OpenAI.return_value = mock_client
        executor = BatchExecutor(data_dir=tmp_path, timeout=60)
        responses = executor._execute_openai(requests, "test_key")

    assert len(responses) == 3
    for i, resp in enumerate(responses):
        assert resp.custom_id == f"r{i}"
        assert resp.content == f"content{i}"
        assert resp.error is None


def test_openai_batch_resumes_existing_pending(tmp_path):
    requests = [_make_openai_req()]
    executor = BatchExecutor(data_dir=tmp_path, timeout=60)
    # Pre-save a pending batch
    executor._save_pending("resume_key", "batch_existing", "openai")

    mock_client = MagicMock()
    mock_batch = MagicMock()
    mock_batch.id = "batch_existing"
    mock_batch.status = "completed"
    mock_batch.output_file_id = "file-out"
    mock_client.batches.retrieve.return_value = mock_batch
    output_line = _make_openai_output_line("r1", "result")
    mock_client.files.content.return_value.content = output_line.encode()

    with patch("winerank.sft.executor.batch.openai") as mock_openai:
        mock_openai.OpenAI.return_value = mock_client
        executor._execute_openai(requests, "resume_key")

    # Should NOT call batches.create (resumed from pending)
    mock_client.batches.create.assert_not_called()
    mock_client.batches.retrieve.assert_called_once_with("batch_existing")


# ---------------------------------------------------------------------------
# Anthropic batch full path (mocked)
# ---------------------------------------------------------------------------

def _make_anthropic_result(custom_id, text):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_input_tokens = 0
    msg.usage = usage

    result_obj = MagicMock()
    result_obj.type = "succeeded"
    result_obj.message = msg

    item = MagicMock()
    item.custom_id = custom_id
    item.result = result_obj
    item.result.type = "succeeded"
    return item


def test_anthropic_batch_submit_poll_collect(tmp_path):
    requests = [_make_anthropic_req(f"a{i}") for i in range(2)]

    mock_client = MagicMock()

    mock_batch = MagicMock()
    mock_batch.id = "msgbatch_123"
    mock_client.messages.batches.create.return_value = mock_batch

    poll_result = MagicMock()
    poll_result.processing_status = "ended"
    poll_result.request_counts.succeeded = 2
    poll_result.request_counts.errored = 0
    poll_result.request_counts.processing = 0
    mock_client.messages.batches.retrieve.return_value = poll_result

    mock_client.messages.batches.results.return_value = [
        _make_anthropic_result(f"a{i}", f"text{i}") for i in range(2)
    ]

    with patch("winerank.sft.executor.batch.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        executor = BatchExecutor(data_dir=tmp_path, timeout=60)
        responses = executor._execute_anthropic(requests, "test_key")

    assert len(responses) == 2
    for i, resp in enumerate(responses):
        assert resp.custom_id == f"a{i}"
        assert resp.content == f"text{i}"
        assert resp.error is None


def test_anthropic_batch_resumes_existing_pending(tmp_path):
    requests = [_make_anthropic_req()]
    executor = BatchExecutor(data_dir=tmp_path, timeout=60)
    executor._save_pending("resume_key_a", "msgbatch_old", "anthropic")

    mock_client = MagicMock()
    poll_result = MagicMock()
    poll_result.processing_status = "ended"
    poll_result.request_counts.succeeded = 1
    poll_result.request_counts.errored = 0
    poll_result.request_counts.processing = 0
    mock_client.messages.batches.retrieve.return_value = poll_result
    mock_client.messages.batches.results.return_value = [
        _make_anthropic_result("a1", "result")
    ]

    with patch("winerank.sft.executor.batch.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        executor._execute_anthropic(requests, "resume_key_a")

    mock_client.messages.batches.create.assert_not_called()
    mock_client.messages.batches.retrieve.assert_called_once_with("msgbatch_old")


# ---------------------------------------------------------------------------
# Mixed requests (both providers)
# ---------------------------------------------------------------------------

def test_batch_executor_routes_by_provider(tmp_path):
    openai_req = _make_openai_req("oai1")
    anthropic_req = _make_anthropic_req("ant1")
    executor = BatchExecutor(data_dir=tmp_path, timeout=60)

    with patch.object(executor, "_execute_openai") as mock_oai, \
         patch.object(executor, "_execute_anthropic") as mock_ant:
        mock_oai.return_value = [LLMResponse("oai1", "oa_content")]
        mock_ant.return_value = [LLMResponse("ant1", "ant_content")]
        responses = executor.execute([openai_req, anthropic_req])

    mock_oai.assert_called_once()
    mock_ant.assert_called_once()
    ids = {r.custom_id: r.content for r in responses}
    assert ids["oai1"] == "oa_content"
    assert ids["ant1"] == "ant_content"


def test_batch_executor_empty_returns_empty(tmp_path):
    executor = BatchExecutor(data_dir=tmp_path)
    assert executor.execute([]) == []


def test_anthropic_batch_strips_markdown_fence_for_json_object(tmp_path):
    """Fence stripping applies to Anthropic batch results for any phase (taxonomy, parse, judge)."""
    requests = [_make_anthropic_req("a0")]  # has response_format={"type": "json_object"}
    fenced = '```json\n{"categories": ["Red", "White"]}\n```'
    mock_client = MagicMock()
    mock_batch = MagicMock()
    mock_batch.id = "msgbatch_123"
    mock_client.messages.batches.create.return_value = mock_batch
    poll_result = MagicMock()
    poll_result.processing_status = "ended"
    poll_result.request_counts.succeeded = 1
    poll_result.request_counts.errored = 0
    poll_result.request_counts.processing = 0
    mock_client.messages.batches.retrieve.return_value = poll_result
    mock_client.messages.batches.results.return_value = [
        _make_anthropic_result("a0", fenced),
    ]
    with patch("winerank.sft.executor.batch.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        executor = BatchExecutor(data_dir=tmp_path, timeout=60)
        responses = executor._execute_anthropic(requests, "test_key")
    assert len(responses) == 1
    assert responses[0].content == '{"categories": ["Red", "White"]}'
    assert responses[0].error is None


def test_openai_batch_strips_markdown_fence_for_json_object(tmp_path):
    """Fence stripping applies to OpenAI batch results when response_format is json_object."""
    req = LLMRequest(
        custom_id="parse__list1__0",
        model="gpt-4o",
        messages=[{"role": "user", "content": "parse"}],
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    fenced = '```json\n{"wines": [{"name": "Chardonnay"}]}\n```'
    mock_batch = MagicMock()
    mock_batch.id = "batch_abc"
    mock_batch.status = "completed"
    mock_batch.output_file_id = "file-out"
    mock_batch.error_file_id = None
    output_lines = [
        json.dumps({
            "custom_id": req.custom_id,
            "response": {
                "body": {
                    "choices": [{"message": {"content": fenced}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                },
            },
            "error": None,
        }),
    ]
    mock_client = MagicMock()
    mock_client.files.content.return_value = MagicMock(content="\n".join(output_lines).encode())
    mock_client.batches.create.return_value = mock_batch
    mock_client.batches.retrieve.return_value = mock_batch
    with patch("winerank.sft.executor.batch.openai") as mock_openai:
        mock_openai.OpenAI.return_value = mock_client
        executor = BatchExecutor(data_dir=tmp_path, timeout=60)
        responses = executor._execute_openai([req], "parse_key")
    assert len(responses) == 1
    assert responses[0].content == '{"wines": [{"name": "Chardonnay"}]}'
    assert responses[0].error is None
