"""Abstract base class for LLM executors."""
from __future__ import annotations

from abc import ABC, abstractmethod

from winerank.sft.executor.types import LLMRequest, LLMResponse


class LLMExecutor(ABC):
    """
    Pluggable LLM execution backend.

    The pipeline builds LLMRequest objects (pure data -- prompts, model names,
    parameters) independently of how they are executed. This class defines the
    single contract: given a list of requests, return a list of responses.

    Two implementations are provided:
    - SyncExecutor: calls litellm.completion() one request at a time (default,
      suitable for development and small runs)
    - BatchExecutor: submits requests to the provider's batch API for a 50%
      cost reduction (suitable for full production runs; async, up to 24h)
    """

    @abstractmethod
    def execute(self, requests: list[LLMRequest]) -> list[LLMResponse]:
        """
        Execute all requests and return responses.

        Responses are returned in the same order as requests. Failed requests
        are represented as LLMResponse objects with error set and empty content,
        rather than raising exceptions, so the pipeline can handle partial
        failures gracefully.

        Args:
            requests: List of LLMRequest objects to execute.

        Returns:
            List of LLMResponse objects, one per request, in the same order.
        """
        ...
