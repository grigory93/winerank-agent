"""Request and response data structures for the LLM executor abstraction."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMRequest:
    """A single LLM completion request, provider-agnostic."""

    custom_id: str
    """Unique identifier used to match responses back to requests."""

    model: str
    """LLM model name (litellm / provider format, e.g. 'claude-opus-4-5', 'gpt-4o')."""

    messages: list[dict]
    """OpenAI-format message list: [{'role': 'system'|'user'|'assistant', 'content': ...}]."""

    max_tokens: int = 4096
    temperature: float = 0.0
    response_format: dict | None = None
    """e.g. {'type': 'json_object'} to request structured JSON output."""

    cache_control_injection_points: list[dict] | None = None
    """Anthropic-specific cache control injection points for prompt caching.

    When set, the SyncExecutor passes this to litellm so that the system
    message and stable taxonomy block are cached across repeated calls,
    reducing cost by up to 90% on cached tokens.

    BatchExecutor injects cache_control blocks directly into the Anthropic
    request payload for the same effect (caching stacks with 50% batch discount).
    """


@dataclass
class LLMResponse:
    """Result of executing a single LLMRequest."""

    custom_id: str
    """Matches the custom_id of the originating LLMRequest."""

    content: str
    """Raw text content returned by the model."""

    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cached": 0})
    """Token counts: {input, output, cached}."""

    error: str | None = None
    """Non-None when the call failed; content will be empty string."""
