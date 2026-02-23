"""Tests for SyncExecutor."""
from unittest.mock import MagicMock, patch

import pytest

from winerank.sft.executor.sync import SyncExecutor
from winerank.sft.executor.types import LLMRequest, LLMResponse


def _make_litellm_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 50):
    """Build a mock litellm response object."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.cache_read_input_tokens = 0
    usage.prompt_tokens_details = None

    choice = MagicMock()
    choice.message.content = content

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def test_sync_executor_returns_one_response_per_request():
    executor = SyncExecutor()
    requests = [
        LLMRequest(custom_id="r1", model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]),
        LLMRequest(custom_id="r2", model="gpt-4o-mini", messages=[{"role": "user", "content": "bye"}]),
    ]
    mock_response = _make_litellm_response('{"status": "OK"}')

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = mock_response
        responses = executor.execute(requests)

    assert len(responses) == 2
    assert responses[0].custom_id == "r1"
    assert responses[1].custom_id == "r2"
    assert mock_litellm.completion.call_count == 2


def test_sync_executor_preserves_response_order():
    executor = SyncExecutor()
    requests = [
        LLMRequest(custom_id=f"r{i}", model="gpt-4o-mini",
                   messages=[{"role": "user", "content": str(i)}])
        for i in range(5)
    ]

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response("ok")
        responses = executor.execute(requests)

    assert [r.custom_id for r in responses] == [f"r{i}" for i in range(5)]


def test_sync_executor_captures_content():
    executor = SyncExecutor()
    req = LLMRequest(
        custom_id="tax__list1",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "analyze this"}],
        response_format={"type": "json_object"},
    )

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response('{"status": "OK", "categories": []}')
        responses = executor.execute([req])

    assert responses[0].content == '{"status": "OK", "categories": []}'
    assert responses[0].error is None


def test_sync_executor_captures_token_counts():
    executor = SyncExecutor()
    req = LLMRequest(custom_id="r1", model="gpt-4o-mini",
                     messages=[{"role": "user", "content": "x"}])

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response("resp", 200, 30)
        responses = executor.execute([req])

    assert responses[0].tokens["input"] == 200
    assert responses[0].tokens["output"] == 30
    assert responses[0].tokens["cached"] == 0


def test_sync_executor_captures_anthropic_cache_tokens():
    executor = SyncExecutor()
    req = LLMRequest(
        custom_id="parse__list1__0",
        model="claude-opus-4-5",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        cache_control_injection_points=[{"location": "system"}],
    )

    usage = MagicMock()
    usage.prompt_tokens = 1000
    usage.completion_tokens = 100
    usage.cache_read_input_tokens = 800

    choice = MagicMock()
    choice.message.content = '{"wines": []}'

    mock_resp = MagicMock()
    mock_resp.choices = [choice]
    mock_resp.usage = usage

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = mock_resp
        responses = executor.execute([req])

    assert responses[0].tokens["cached"] == 800
    # Verify cache_control_injection_points was passed through
    call_kwargs = mock_litellm.completion.call_args[1]
    assert "cache_control_injection_points" in call_kwargs


def test_sync_executor_does_not_inject_cache_for_openai():
    executor = SyncExecutor()
    req = LLMRequest(
        custom_id="r1",
        model="gpt-4o",
        messages=[{"role": "user", "content": "x"}],
        cache_control_injection_points=[{"location": "system"}],
    )

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response("ok")
        executor.execute([req])

    call_kwargs = mock_litellm.completion.call_args[1]
    # OpenAI uses automatic caching, so we should NOT inject cache_control_injection_points
    assert "cache_control_injection_points" not in call_kwargs


def test_sync_executor_handles_call_failure_gracefully():
    executor = SyncExecutor()
    requests = [
        LLMRequest(custom_id="ok", model="gpt-4o-mini",
                   messages=[{"role": "user", "content": "hi"}]),
        LLMRequest(custom_id="fail", model="gpt-4o-mini",
                   messages=[{"role": "user", "content": "bye"}]),
    ]

    def side_effect(**kwargs):
        content = kwargs["messages"][0]["content"]
        if content == "bye":
            raise RuntimeError("API error")
        return _make_litellm_response("ok")

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = side_effect
        responses = executor.execute(requests)

    assert len(responses) == 2
    assert responses[0].custom_id == "ok"
    assert responses[0].error is None
    assert responses[1].custom_id == "fail"
    assert responses[1].error is not None
    assert responses[1].content == ""


def test_sync_executor_empty_requests_returns_empty():
    executor = SyncExecutor()
    responses = executor.execute([])
    assert responses == []


def test_sync_executor_passes_response_format():
    executor = SyncExecutor()
    req = LLMRequest(
        custom_id="r1", model="gpt-4o-mini",
        messages=[{"role": "user", "content": "x"}],
        response_format={"type": "json_object"},
    )

    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response("{}")
        executor.execute([req])

    call_kwargs = mock_litellm.completion.call_args[1]
    assert call_kwargs["response_format"] == {"type": "json_object"}


def test_sync_executor_strips_markdown_fence_for_json_object_all_phases():
    """Fence stripping applies to any phase (taxonomy, parse, judge) when response_format is json_object."""
    executor = SyncExecutor()
    fenced = '```json\n{"score": 0.9, "recommendation": "accept"}\n```'
    req = LLMRequest(
        custom_id="judge__list1__0",
        model="claude-opus-4-6",
        messages=[{"role": "user", "content": "judge this"}],
        response_format={"type": "json_object"},
    )
    with patch("winerank.sft.executor.sync.litellm") as mock_litellm:
        mock_litellm.completion.return_value = _make_litellm_response(fenced)
        responses = executor.execute([req])
    assert responses[0].content == '{"score": 0.9, "recommendation": "accept"}'
    assert responses[0].error is None
