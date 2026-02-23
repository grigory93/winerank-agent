"""Tests for LLMRequest and LLMResponse dataclasses."""
from winerank.sft.executor.types import LLMRequest, LLMResponse


def test_llm_request_defaults():
    req = LLMRequest(
        custom_id="test-1",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert req.custom_id == "test-1"
    assert req.model == "gpt-4o-mini"
    assert req.max_tokens == 4096
    assert req.temperature == 0.0
    assert req.response_format is None
    assert req.cache_control_injection_points is None


def test_llm_request_with_all_fields():
    req = LLMRequest(
        custom_id="tax__list1",
        model="claude-opus-4-5",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        max_tokens=2048,
        temperature=0.1,
        response_format={"type": "json_object"},
        cache_control_injection_points=[{"location": "system"}],
    )
    assert req.max_tokens == 2048
    assert req.temperature == 0.1
    assert req.response_format == {"type": "json_object"}
    assert req.cache_control_injection_points == [{"location": "system"}]


def test_llm_response_defaults():
    resp = LLMResponse(custom_id="test-1", content="hello")
    assert resp.custom_id == "test-1"
    assert resp.content == "hello"
    assert resp.tokens == {"input": 0, "output": 0, "cached": 0}
    assert resp.error is None


def test_llm_response_error():
    resp = LLMResponse(
        custom_id="test-1",
        content="",
        tokens={"input": 0, "output": 0, "cached": 0},
        error="Connection timeout",
    )
    assert resp.error == "Connection timeout"
    assert resp.content == ""


def test_llm_response_with_tokens():
    resp = LLMResponse(
        custom_id="parse__list1__0",
        content='{"wines": []}',
        tokens={"input": 1000, "output": 50, "cached": 800},
    )
    assert resp.tokens["input"] == 1000
    assert resp.tokens["output"] == 50
    assert resp.tokens["cached"] == 800


def test_create_executor_returns_sync_by_default():
    from winerank.sft.executor import create_executor
    from winerank.sft.executor.sync import SyncExecutor

    executor = create_executor(batch_mode=False)
    assert isinstance(executor, SyncExecutor)


def test_create_executor_returns_batch_when_requested(tmp_path):
    from winerank.sft.executor import create_executor
    from winerank.sft.executor.batch import BatchExecutor

    executor = create_executor(batch_mode=True, data_dir=tmp_path)
    assert isinstance(executor, BatchExecutor)
