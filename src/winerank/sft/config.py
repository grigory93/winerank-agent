"""SFT training data generation configuration."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SFTSettings(BaseSettings):
    """Settings for the SFT training data generation pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WINERANK_SFT_",
        case_sensitive=False,
        extra="ignore",
    )

    # Model configuration
    taxonomy_model: str = Field(
        default="gpt-4o-mini",
        description="Cheap LLM for wine list validation and taxonomy extraction",
    )
    teacher_model: str = Field(
        # default="claude-opus-4-5",
        default="gpt-5.2",
        description="Powerful LLM for gold-pass wine parsing",
    )
    judge_model: str = Field(
        default="claude-opus-4-6",
        description="Powerful LLM for optional judge review pass",
    )

    # Input/output mode for wine parsing
    training_data_mode: Literal["vision", "text"] = Field(
        default="vision",
        description="Input mode for wine parsing: 'vision' (page images) or 'text' (extracted text)",
    )

    # Sampling configuration
    num_samples: int = Field(
        default=500,
        description="Target number of training samples",
    )
    seed: int = Field(
        default=42,
        description="Random seed for reproducible sampling",
    )
    min_segment_chars: int = Field(
        default=50,
        description="Minimum characters for a segment to be included (filters blank pages)",
    )
    min_segments_per_list: int = Field(
        default=2,
        description="Minimum segments sampled from each valid wine list",
    )

    # Path configuration
    data_dir: str = Field(
        default="data/sft",
        description="Root directory for SFT data output",
    )
    examples_dir: str = Field(
        default="data/examples",
        description="Directory containing wine list files",
    )

    # Dataset build options
    min_judge_score: float = Field(
        default=0.0,
        description="Minimum judge score for sample inclusion in final dataset (0.0 = include all)",
    )

    # Correction loop options
    max_correction_rounds: int = Field(
        default=2,
        description=(
            "Maximum Teacher correction rounds using Judge feedback. "
            "0 disables the correction loop entirely. "
            "Env: WINERANK_SFT_MAX_CORRECTION_ROUNDS"
        ),
    )

    # Batch execution options
    batch_mode: bool = Field(
        default=False,
        description=(
            "Use provider-native batch APIs for 50%% cost reduction. "
            "Async -- may take up to 24h. "
            "Env: WINERANK_SFT_BATCH_MODE=true"
        ),
    )
    batch_timeout: int = Field(
        default=7200,
        description="Max seconds to wait for a batch to complete (default 2 hours)",
    )

    @field_validator("training_data_mode", mode="before")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = str(v).lower()
        if v not in ("vision", "text"):
            raise ValueError(f"training_data_mode must be 'vision' or 'text', got {v!r}")
        return v

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def taxonomy_dir(self) -> Path:
        return self.data_path / "taxonomy"

    @property
    def parsed_dir(self) -> Path:
        return self.data_path / "parsed"

    @property
    def judged_dir(self) -> Path:
        return self.data_path / "judged"

    @property
    def corrected_dir(self) -> Path:
        """Directory for correction snapshots (original parse saved before overwrite)."""
        return self.data_path / "corrected"

    @property
    def dataset_dir(self) -> Path:
        return self.data_path / "dataset"

    @property
    def samples_file(self) -> Path:
        return self.data_path / "samples.json"

    @property
    def progress_file(self) -> Path:
        return self.data_path / "progress.json"

    @property
    def manifest_file(self) -> Path:
        return self.data_path / "manifest.yaml"

    def ensure_dirs(self) -> None:
        """Create all required output directories."""
        for d in [
            self.data_path,
            self.taxonomy_dir,
            self.parsed_dir,
            self.judged_dir,
            self.corrected_dir,
            self.dataset_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_sft_settings() -> SFTSettings:
    """Get cached SFT settings instance."""
    return SFTSettings()
