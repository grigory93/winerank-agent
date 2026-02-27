"""Prompt templates for SFT training data generation pipeline."""

# ---------------------------------------------------------------------------
# Taxonomy extraction prompt
# ---------------------------------------------------------------------------

TAXONOMY_SYSTEM_PROMPT = """\
You are a wine list analyst. Your job is to analyze wine list documents and:
1. Determine if the document is a wine list containing multiple wines with prices.
2. If it is a wine list, extract its hierarchical category taxonomy.

You will respond with a JSON object. Do not include any explanation or text outside of the JSON.
"""

TAXONOMY_USER_PROMPT = """\
Analyze the following document text and respond with a JSON object.

STEP 1: Determine if this is a wine list.
A wine list must contain:
- Multiple distinct wine entries (not just a few passing mentions)
- Prices for the wines
- Wine-specific attributes (varietals, regions, vintages, producers, etc.)

STEP 2: If it IS a wine list, extract the hierarchical taxonomy of wine categories.
- Scan the entire text for section headings, category titles, sub-section headings, and structural groupings
- Include categories found in a table of contents AND categories inferred from the document structure (section headers, subsection dividers, etc.)
- Do NOT include page numbers
- Do NOT include individual wine names
- Produce a clean hierarchical structure of wine categories

RESPONSE FORMAT:
If NOT a wine list:
{{"status": "NOT_A_LIST"}}

If IS a wine list:
{{
  "status": "OK",
  "restaurant_name": "Restaurant Name or null",
  "categories": [
    {{
      "name": "Category Name",
      "subcategories": [
        {{"name": "Subcategory Name", "subcategories": []}}
      ]
    }}
  ]
}}

DOCUMENT TEXT:
{full_text}
"""


# ---------------------------------------------------------------------------
# Wine parsing prompts
# ---------------------------------------------------------------------------

WINE_PARSING_SYSTEM_PROMPT = """\
You are a precise wine data extraction model. Parse the raw text from a wine list \
into structured JSON. Each wine entry must include all identifiable attributes from \
the schema below.

Be extremely accurate in identifying wine attributes -- try to map all information \
present but do NOT fabricate missing information unless it is absolutely obvious from \
context (e.g., "Sonoma" or "Napa Valley" imply country "United States"; "Barolo" \
implies country "Italy", region "Piedmont").

WINE ATTRIBUTES SCHEMA:
- name (required): The specific brand name of the wine
- list_identifier: Internal wine ID from the list (bin number, SKU, code)
- winery: The producer/estate name
- varietal: The grape variety or blend (e.g. Pinot Noir, Cabernet Sauvignon, Champagne Blend)
- wine_type: The category of wine (e.g. Red, White, Rose, Sparkling, Dessert, \
Fortified, Orange, Sake, Natural -- not limited to these values)
- country: Country of origin
- region: Broad area (e.g. California, Bordeaux, Burgundy)
- sub_region: Nested area (e.g. Sonoma County, Cote de Nuits)
- appellation: Legal geographic designation such as AVA, AOC, DOC, DOCG, DO, VDP, etc. \
(e.g. Russian River Valley, Saint-Julien, Barolo -- not limited to these examples)
- designation: Special title (Reserve, Grand Cru, Estate Bottled, etc.)
- vineyard: Named vineyard if specified
- vintage: Year or "NV" for non-vintage
- format: Bottle size or serving format (750ml, by the glass, magnum, etc.)
- price: Numeric price in local currency (number only, no currency symbols)
- note: Any additional info (tasting notes, sommelier comments, etc.)

CRITICAL RULES FOR CONSISTENCY:
- varietal, wine_type, country, region, sub_region, appellation, and designation are \
STANDARDIZED fields used to match the same wine across different restaurant lists. \
Use canonical, widely-recognized values.
- Infer wine_type, country, region, sub_region, appellation from the VALID CATEGORIES \
context and your wine knowledge when the page text does not state them explicitly.
- Do NOT invent wines. Only extract wines that appear in the text.
- Return a JSON object: {"wines": [...]}
- If no wines are found in the text, return: {"wines": []}
"""

WINE_PARSING_USER_PROMPT = """\
The following taxonomy was extracted from this wine list by analyzing its table of \
contents (if present) and the structural organization of wine sections, headers, and \
groupings throughout the document. Use it to resolve section context, wine type, \
region, and other attributes that may not be explicit in the text below.

VALID CATEGORIES:
{taxonomy_text}

RAW TEXT TO PARSE:
{segment_text}
"""


# ---------------------------------------------------------------------------
# Judge review prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are an expert wine sommelier and data quality reviewer. Your job is to assess \
whether a wine parsing model correctly extracted wine data from a wine list segment.

You will be given:
1. The original wine list segment (text, and a page image when available for PDF sources)
2. The taxonomy (valid categories) for this wine list
3. The parsed JSON output from the model

When a page image is provided, use it as the primary source of truth for verifying \
wine entries and their attributes. The text extraction may be incomplete or garbled \
for complex layouts (columns, tables, decorative fonts). Cross-reference the image \
with the parsed output to catch missing wines, hallucinations, and attribute errors.

Evaluate the parsing quality and respond with a JSON object. Do not include any \
text outside the JSON.
"""

JUDGE_USER_PROMPT = """\
Review the following wine parsing result for accuracy and completeness.

ORIGINAL TEXT SEGMENT:
{segment_text}

VALID CATEGORIES (taxonomy):
{taxonomy_text}

PARSED OUTPUT (model result):
{parsed_json}

Evaluate (use the page image as primary reference when provided):
1. Are all wines from the segment present in the parsed output? (no missing wines)
2. Are there any wines in the output that do NOT appear in the segment? (no hallucinations)
3. Are the wine attributes (name, winery, varietal, region, appellation, vintage, price) \
correctly parsed?
4. Is the wine_type correctly identified based on the segment and taxonomy context?
5. Are prices correctly parsed (numeric, correct values)?

Respond with this JSON format:
{{
  "score": <float 0.0-1.0>,
  "wine_count_match": <true/false>,
  "issues": [
    {{
      "type": "missing_wine|hallucinated_wine|wrong_attribute|wrong_price|other",
      "description": "human-readable explanation",
      "wine_name": "name of affected wine or null",
      "field": "affected attribute name or null",
      "current_value": "what the model produced or null",
      "expected_value": "what the correct value should be or null"
    }}
  ],
  "needs_reparse": <true/false>,
  "recommendation": "accept|review|reject"
}}

Issue types:
- "missing_wine": A wine present in the text was not extracted
- "hallucinated_wine": A wine in the output does not appear in the text
- "wrong_attribute": A specific attribute (varietal, region, appellation, etc.) is incorrect
- "wrong_price": Price value is wrong (e.g., 850 instead of 85, missing decimal)
- "other": Any other quality issue

Set "needs_reparse" to true when:
- Any wines are missing or hallucinated
- Multiple wrong attributes on the same wine
- Structural errors that require re-examining the full segment

Set "needs_reparse" to false when:
- Only minor, isolated attribute corrections are needed

Score guidelines:
- 0.9-1.0: Excellent, all wines correctly parsed with accurate attributes
- 0.7-0.9: Good, minor attribute errors but all wines found
- 0.5-0.7: Fair, some wines missing or significant attribute errors
- 0.3-0.5: Poor, many wines missing or major errors
- 0.0-0.3: Very poor, fundamental parsing failures

Recommendation guidelines:
- "accept": Score >= 0.8, suitable for training data as-is
- "review": Score 0.5-0.8, human review recommended before inclusion
- "reject": Score < 0.5, not suitable for training data
"""


# ---------------------------------------------------------------------------
# Correction prompts
# ---------------------------------------------------------------------------

# NOTE: CORRECTION_SYSTEM_PROMPT intentionally reuses WINE_PARSING_SYSTEM_PROMPT
# so that the system message prefix is identical and prompt caching applies
# across both initial parse requests and correction requests.
CORRECTION_USER_PROMPT = """\
The following taxonomy was extracted from this wine list by analyzing its table of \
contents (if present) and the structural organization of wine sections, headers, and \
groupings throughout the document. Use it to resolve section context, wine type, \
region, and other attributes that may not be explicit in the text below.

VALID CATEGORIES:
{taxonomy_text}

RAW TEXT TO PARSE:
{segment_text}

PREVIOUS PARSE ATTEMPT (contains errors):
{previous_json}

QUALITY REVIEW ISSUES IDENTIFIED:
{issues_text}

Re-parse the raw text above and produce a corrected JSON output. \
Fix ALL identified issues while keeping correctly-extracted wines intact. \
Do not remove any wine that was correctly extracted in the previous attempt. \
Do not add wines that do not appear in the raw text.
"""


def _format_issues_for_correction(issues: list) -> str:
    """Format structured JudgeIssue objects (or dicts) into readable correction guidance."""
    if not issues:
        return "(no specific issues provided)"
    lines = []
    for i, issue in enumerate(issues, 1):
        if isinstance(issue, dict):
            itype = issue.get("type", "other")
            desc = issue.get("description", "")
            wine = issue.get("wine_name")
            field = issue.get("field")
            current = issue.get("current_value")
            expected = issue.get("expected_value")
        else:
            itype = getattr(issue, "type", "other")
            desc = getattr(issue, "description", "")
            wine = getattr(issue, "wine_name", None)
            field = getattr(issue, "field", None)
            current = getattr(issue, "current_value", None)
            expected = getattr(issue, "expected_value", None)

        line = f"{i}. [{itype.upper()}] {desc}"
        if wine:
            line += f" (wine: {wine!r})"
        if field and (current or expected):
            line += f" | {field}: {current!r} -> {expected!r}"
        lines.append(line)
    return "\n".join(lines)


def build_correction_messages(
    taxonomy_text: str,
    segment_text: str,
    previous_json: str,
    issues: list,
    segment_image_b64: str | None = None,
) -> list[dict]:
    """
    Build messages for a correction request.

    Reuses WINE_PARSING_SYSTEM_PROMPT as the system message so that the
    system prefix is identical to the original parse request -- enabling
    prompt cache hits on both Anthropic and OpenAI.
    """
    issues_text = _format_issues_for_correction(issues)
    user_content: list[dict] = [
        {
            "type": "text",
            "text": CORRECTION_USER_PROMPT.format(
                taxonomy_text=taxonomy_text,
                segment_text=segment_text,
                previous_json=previous_json,
                issues_text=issues_text,
            ),
        }
    ]

    if segment_image_b64 is not None:
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{segment_image_b64}"},
            },
            *user_content,
        ]

    return [
        {"role": "system", "content": WINE_PARSING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_taxonomy_prompt(full_text: str) -> list[dict]:
    """Build the messages list for taxonomy extraction."""
    return [
        {"role": "system", "content": TAXONOMY_SYSTEM_PROMPT},
        {"role": "user", "content": TAXONOMY_USER_PROMPT.format(full_text=full_text)},
    ]


def build_wine_parsing_messages(
    taxonomy_text: str,
    segment_text: str,
    segment_image_b64: str | None = None,
) -> list[dict]:
    """
    Build the messages list for wine parsing.

    The system message and the taxonomy block are kept stable across calls so
    that prompt caching (Anthropic ephemeral cache, OpenAI automatic prefix
    caching) can kick in for the expensive repeated tokens.
    """
    user_content: list[dict] = [
        {
            "type": "text",
            "text": WINE_PARSING_USER_PROMPT.format(
                taxonomy_text=taxonomy_text,
                segment_text=segment_text,
            ),
        }
    ]

    if segment_image_b64 is not None:
        # Prepend image content block for vision mode
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{segment_image_b64}"},
            },
            *user_content,
        ]

    return [
        {"role": "system", "content": WINE_PARSING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_judge_messages(
    segment_text: str,
    taxonomy_text: str,
    parsed_json: str,
    segment_image_b64: str | None = None,
) -> list[dict]:
    """Build the messages list for judge review.

    When ``segment_image_b64`` is provided (vision mode, PDF sources), the page
    image is prepended to the user message so the Judge can cross-reference the
    parsed output against the original page layout.
    """
    user_content: list[dict] = [
        {
            "type": "text",
            "text": JUDGE_USER_PROMPT.format(
                segment_text=segment_text,
                taxonomy_text=taxonomy_text,
                parsed_json=parsed_json,
            ),
        }
    ]

    if segment_image_b64 is not None:
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{segment_image_b64}"},
            },
            *user_content,
        ]

    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
