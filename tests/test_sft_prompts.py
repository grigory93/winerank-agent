"""Tests for SFT prompt templates."""
from winerank.sft.prompts import (
    JUDGE_SYSTEM_PROMPT,
    TAXONOMY_SYSTEM_PROMPT,
    TAXONOMY_USER_PROMPT,
    WINE_PARSING_SYSTEM_PROMPT,
    WINE_PARSING_USER_PROMPT,
    build_judge_messages,
    build_taxonomy_prompt,
    build_wine_parsing_messages,
)


# ---------------------------------------------------------------------------
# Taxonomy prompts
# ---------------------------------------------------------------------------


def test_taxonomy_system_prompt_content():
    assert "wine list" in TAXONOMY_SYSTEM_PROMPT.lower()
    assert "json" in TAXONOMY_SYSTEM_PROMPT.lower()


def test_taxonomy_user_prompt_has_placeholder():
    assert "{full_text}" in TAXONOMY_USER_PROMPT


def test_taxonomy_user_prompt_format():
    formatted = TAXONOMY_USER_PROMPT.format(full_text="some wine text")
    assert "some wine text" in formatted
    assert "NOT_A_LIST" in formatted
    assert "categories" in formatted


def test_build_taxonomy_prompt_structure():
    messages = build_taxonomy_prompt("wine list text here")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "wine list text here" in messages[1]["content"]


# ---------------------------------------------------------------------------
# Wine parsing prompts
# ---------------------------------------------------------------------------


def test_wine_parsing_system_prompt_has_schema():
    prompt = WINE_PARSING_SYSTEM_PROMPT
    # All required schema fields
    for field in ["name", "winery", "varietal", "wine_type", "country", "region",
                  "appellation", "designation", "vintage", "price"]:
        assert field in prompt, f"Missing field {field!r} in system prompt"


def test_wine_parsing_system_prompt_precision():
    assert "extremely accurate" in WINE_PARSING_SYSTEM_PROMPT.lower()
    assert "fabricate" in WINE_PARSING_SYSTEM_PROMPT.lower()


def test_wine_parsing_system_prompt_wine_type_not_limited():
    assert "not limited" in WINE_PARSING_SYSTEM_PROMPT.lower()


def test_wine_parsing_user_prompt_placeholders():
    assert "{taxonomy_text}" in WINE_PARSING_USER_PROMPT
    assert "{segment_text}" in WINE_PARSING_USER_PROMPT


def test_wine_parsing_user_prompt_taxonomy_attribution():
    # Correct attribution: mentions both TOC and structural analysis
    assert "table of contents" in WINE_PARSING_USER_PROMPT.lower()
    assert "structural" in WINE_PARSING_USER_PROMPT.lower()


def test_build_wine_parsing_messages_text_mode():
    messages = build_wine_parsing_messages(
        taxonomy_text="- Champagne\n- Red Wines",
        segment_text="Krug NV $450",
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == WINE_PARSING_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"

    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    assert len(user_content) == 1
    assert user_content[0]["type"] == "text"
    assert "Krug NV $450" in user_content[0]["text"]
    assert "Champagne" in user_content[0]["text"]


def test_build_wine_parsing_messages_vision_mode():
    fake_b64 = "aGVsbG8="  # base64("hello")
    messages = build_wine_parsing_messages(
        taxonomy_text="- Red",
        segment_text="Wine text",
        segment_image_b64=fake_b64,
    )
    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    assert len(user_content) == 2
    # First block should be the image
    assert user_content[0]["type"] == "image_url"
    assert fake_b64 in user_content[0]["image_url"]["url"]
    # Second block should be text
    assert user_content[1]["type"] == "text"


def test_build_wine_parsing_messages_system_is_string():
    """System message should be a plain string for caching to work correctly."""
    messages = build_wine_parsing_messages("taxonomy", "segment")
    assert isinstance(messages[0]["content"], str)


# ---------------------------------------------------------------------------
# Judge prompts
# ---------------------------------------------------------------------------


def test_judge_system_prompt_content():
    assert "sommelier" in JUDGE_SYSTEM_PROMPT.lower() or "reviewer" in JUDGE_SYSTEM_PROMPT.lower()
    assert "json" in JUDGE_SYSTEM_PROMPT.lower()


def test_build_judge_messages_structure():
    messages = build_judge_messages(
        segment_text="Dom Perignon 2015 $350",
        taxonomy_text="Champagne",
        parsed_json='{"wines": [{"name": "Dom Perignon"}]}',
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "Dom Perignon 2015 $350" in user_content
    assert "Champagne" in user_content
    assert "Dom Perignon" in user_content


def test_judge_user_prompt_has_score_guidelines():
    from winerank.sft.prompts import JUDGE_USER_PROMPT
    assert "score" in JUDGE_USER_PROMPT.lower()
    assert "recommendation" in JUDGE_USER_PROMPT.lower()
    assert "accept" in JUDGE_USER_PROMPT.lower()
    assert "reject" in JUDGE_USER_PROMPT.lower()
