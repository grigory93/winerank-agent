"""Parse a raw address string into structured fields using an LLM."""
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AddressParts(BaseModel):
    """Structured address components from LLM parsing."""

    address: Optional[str] = Field(default=None, description="Street address (number + street)")
    city: Optional[str] = Field(default=None, description="City")
    state: Optional[str] = Field(default=None, description="State or region")
    zip: Optional[str] = Field(default=None, description="Postal / ZIP code")
    country: Optional[str] = Field(default=None, description="Country")


def parse_address_with_llm(
    raw_address: str,
    *,
    llm_fn=None,
    api_key: Optional[str] = None,
    model: str = "openai/gpt-4o-mini",
    temperature: float = 0.0,
    max_tokens: int = 200,
) -> AddressParts:
    """
    Parse a raw address string into AddressParts using an LLM.

    Falls back to AddressParts(address=raw_address) when:
    - llm_fn is None (LiteLLM not installed)
    - the LLM call raises any exception

    When api_key is empty the kwarg is omitted so LiteLLM can fall back
    to a provider environment variable (e.g. OPENAI_API_KEY).
    """
    if not raw_address or not raw_address.strip():
        return AddressParts()

    if not llm_fn:
        logger.debug("LLM not available for address parsing, using fallback")
        return AddressParts(address=raw_address.strip())

    prompt = (
        "Extract address components from the text below.\n"
        "Return a JSON object with exactly these keys: "
        "address (street number + street name only), city, state, zip, country.\n"
        "Use null for any value that is absent.\n\n"
        f"Text:\n{raw_address.strip()}"
    )

    try:
        kwargs: dict = dict(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an address parser. "
                        "Respond with a JSON object only – no prose, no markdown fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if api_key:
            kwargs["api_key"] = api_key

        response = llm_fn(**kwargs)
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        return AddressParts.model_validate(data)
    except Exception as e:
        logger.warning("Address LLM parse failed: %s", e)
        return AddressParts(address=raw_address.strip())
