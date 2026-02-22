"""Pydantic schemas for SFT training data pipeline."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Taxonomy schemas
# ---------------------------------------------------------------------------


class TaxonomyNode(BaseModel):
    """A node in the hierarchical wine category taxonomy."""

    name: str
    subcategories: list[TaxonomyNode] = Field(default_factory=list)

    def flat_list(self, prefix: str = "") -> list[str]:
        """Return all category names as a flat list with hierarchical path."""
        full_name = f"{prefix} > {self.name}" if prefix else self.name
        result = [full_name]
        for sub in self.subcategories:
            result.extend(sub.flat_list(prefix=full_name))
        return result

    def to_text(self, indent: int = 0) -> str:
        """Return human-readable indented text representation."""
        lines = ["  " * indent + f"- {self.name}"]
        for sub in self.subcategories:
            lines.append(sub.to_text(indent + 1))
        return "\n".join(lines)


class TaxonomyResult(BaseModel):
    """Result of taxonomy extraction for a single wine list."""

    status: Literal["OK", "NOT_A_LIST"]
    restaurant_name: Optional[str] = None
    categories: list[TaxonomyNode] = Field(default_factory=list)
    source_file: Optional[str] = None

    def flat_categories(self) -> list[str]:
        """Return all categories as a flat list of hierarchical paths."""
        result = []
        for cat in self.categories:
            result.extend(cat.flat_list())
        return result

    def to_prompt_text(self) -> str:
        """Format categories for injection into wine parsing prompt."""
        if not self.categories:
            return "(no taxonomy available)"
        lines = []
        for cat in self.categories:
            lines.append(cat.to_text())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Segment / page schemas
# ---------------------------------------------------------------------------


class WineSegment(BaseModel):
    """A single parsed segment (page or HTML section) from a wine list."""

    list_id: str
    segment_index: int
    segment_text: str
    page_image_path: Optional[str] = None  # path to rendered page image (vision mode)
    source_file: str
    file_type: Literal["pdf", "html"]
    char_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        if not self.char_count:
            self.char_count = len(self.segment_text)


class SampleManifestEntry(BaseModel):
    """Reference to a sampled segment (used in samples.json)."""

    list_id: str
    segment_index: int
    source_file: str
    file_type: Literal["pdf", "html"]
    char_count: int


# ---------------------------------------------------------------------------
# Wine parsing result schemas
# ---------------------------------------------------------------------------


class WineEntry(BaseModel):
    """A single parsed wine entry (mirrors Wine ORM model attributes)."""

    name: str
    list_identifier: Optional[str] = None
    winery: Optional[str] = None
    varietal: Optional[str] = None
    wine_type: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    sub_region: Optional[str] = None
    appellation: Optional[str] = None
    designation: Optional[str] = None
    vineyard: Optional[str] = None
    vintage: Optional[str] = None
    format: Optional[str] = None
    price: Optional[float] = None
    note: Optional[str] = None


class PageParseResult(BaseModel):
    """Result of parsing a single segment via the Teacher model."""

    segment_id: str  # "{list_id}_{segment_index}"
    list_id: str
    segment_index: int
    source_file: str
    segment_text: str
    taxonomy_text: str
    wines: list[WineEntry] = Field(default_factory=list)
    raw_response: Optional[str] = None
    parse_error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    model_used: Optional[str] = None


# ---------------------------------------------------------------------------
# Judge review schemas
# ---------------------------------------------------------------------------


class JudgeResult(BaseModel):
    """Result of the optional Judge model review pass."""

    segment_id: str
    list_id: str
    segment_index: int
    score: float = Field(ge=0.0, le=1.0, description="Overall correctness 0.0-1.0")
    wine_count_match: bool = Field(description="Did Teacher find the right number of wines?")
    issues: list[str] = Field(default_factory=list, description="Specific problems found")
    recommendation: Literal["accept", "review", "reject"]
    raw_response: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: Optional[str] = None

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ---------------------------------------------------------------------------
# Manifest schemas
# ---------------------------------------------------------------------------


class ManifestEntry(BaseModel):
    """A single wine list entry in the manifest."""

    list_id: str
    restaurant_name: str
    file_path: str
    file_type: Literal["pdf", "html"]
    notes: Optional[str] = None


class Manifest(BaseModel):
    """Full wine list manifest."""

    lists: list[ManifestEntry] = Field(default_factory=list)

    def get_entry(self, list_id: str) -> Optional[ManifestEntry]:
        for entry in self.lists:
            if entry.list_id == list_id:
                return entry
        return None


# ---------------------------------------------------------------------------
# Dataset build schemas
# ---------------------------------------------------------------------------


class TrainingSample(BaseModel):
    """A single SFT training example in OpenAI chat-completion format."""

    messages: list[dict[str, str]]
    metadata: Optional[dict[str, Any]] = None


class DatasetMetadata(BaseModel):
    """Metadata written alongside the JSONL training file."""

    generated_at: str
    taxonomy_model: str
    teacher_model: str
    judge_model: Optional[str] = None
    training_data_mode: str
    num_samples_target: int
    num_samples_actual: int
    num_lists_used: int
    not_a_list_count: int
    judge_filtered_count: int
    seed: int
    min_judge_score: float
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
