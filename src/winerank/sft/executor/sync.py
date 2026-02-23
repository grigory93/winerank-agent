"""Synchronous LLM executor using litellm.completion()."""
from __future__ import annotations

import logging
import re

import litellm  # type: ignore[import-untyped]

from winerank.sft.executor.base import LLMExecutor
from winerank.sft.executor.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


def _strip_markdown_fence(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences that some LLMs wrap around JSON."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or "anthropic" in model.lower()


def _is_openai_model(model: str) -> bool:
    m = model.lower().lstrip("openai/")
    return m.startswith(("gpt-", "o1", "o3", "o4")) or "openai" in model.lower()


def _extract_cached_tokens(usage: object, model: str) -> int:
    """Extract cached token count from a litellm usage object."""
    if _is_anthropic_model(model):
        return int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    if details:
        return int(getattr(details, "cached_tokens", 0) or 0)
    return 0


class SyncExecutor(LLMExecutor):
    """
    Executes LLM requests one at a time via litellm.completion().

    This is the default executor for development, testing, and --limit runs.
    Results are available immediately after each call, making it easy to
    inspect intermediate results and resume from progress.json.

    Prompt caching is applied automatically:
    - Anthropic models: cache_control_injection_points are passed to litellm
      when the request includes them, reducing repeated system+taxonomy tokens
      by up to 90%.
    - OpenAI models: prefix caching is automatic for prompts sharing a common
      prefix (no explicit opt-in required).
    """

    def execute(self, requests: list[LLMRequest]) -> list[LLMResponse]:
        """Execute all requests sequentially. Returns one response per request."""
        responses: list[LLMResponse] = []
        total = len(requests)

        for i, req in enumerate(requests, 1):
            logger.info("[%d/%d] Calling %s (id=%s)", i, total, req.model, req.custom_id)
            try:
                kwargs: dict = {
                    "model": req.model,
                    "messages": req.messages,
                    "temperature": req.temperature,
                }
                if _is_openai_model(req.model):
                    kwargs["max_completion_tokens"] = req.max_tokens
                else:
                    kwargs["max_tokens"] = req.max_tokens
                if req.response_format is not None:
                    kwargs["response_format"] = req.response_format

                if req.cache_control_injection_points and _is_anthropic_model(req.model):
                    kwargs["cache_control_injection_points"] = req.cache_control_injection_points

                response = litellm.completion(**kwargs)
                content: str = response.choices[0].message.content or ""
                if req.response_format == {"type": "json_object"}:
                    content = _strip_markdown_fence(content)
                usage = response.usage or {}
                tokens = {
                    "input": getattr(usage, "prompt_tokens", 0),
                    "output": getattr(usage, "completion_tokens", 0),
                    "cached": _extract_cached_tokens(usage, req.model),
                }
                responses.append(LLMResponse(
                    custom_id=req.custom_id,
                    content=content,
                    tokens=tokens,
                ))
                logger.debug(
                    "[%s] tokens: in=%d out=%d cached=%d",
                    req.custom_id, tokens["input"], tokens["output"], tokens["cached"],
                )
            except Exception as exc:
                logger.error("[%s] Call failed: %s", req.custom_id, exc)
                responses.append(LLMResponse(
                    custom_id=req.custom_id,
                    content="",
                    tokens={"input": 0, "output": 0, "cached": 0},
                    error=str(exc),
                ))

        return responses
