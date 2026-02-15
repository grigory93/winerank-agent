"""Configuration management using pydantic-settings."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WINERANK_",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://winerank:winerank@localhost:5432/winerank",
        description="PostgreSQL connection URL",
    )

    # Crawler settings
    michelin_level: str = Field(
        default="3",
        description="Michelin distinction level: 3, 2, 1, gourmand, selected, all",
    )
    restaurant_website_depth: int = Field(
        default=4,
        description="Maximum link depth when navigating restaurant websites",
    )
    max_restaurant_pages: int = Field(
        default=20,
        description="Maximum number of pages to check per restaurant site",
    )
    crawler_concurrency: int = Field(
        default=3,
        description="Number of parallel restaurant crawls",
    )
    download_dir: str = Field(
        default="data/downloads",
        description="Directory for downloaded wine lists",
    )

    # LLM settings (optional, for future crawler navigation fallback)
    llm_provider: str = Field(
        default="openai",
        description="LLM provider: openai, anthropic, gemini, etc.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="LLM model name",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for LLM provider",
    )
    use_llm_navigation: bool = Field(
        default=False,
        description="Enable LLM-assisted restaurant site navigation",
    )

    # Playwright settings
    headless: bool = Field(
        default=True,
        description="Run browser in headless mode",
    )
    browser_timeout: int = Field(
        default=30000,
        description="Browser timeout in milliseconds",
    )

    @property
    def download_path(self) -> Path:
        """Get download directory as Path object."""
        path = Path(self.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_michelin_distinction_slug(self) -> str:
        """Convert michelin_level to URL slug for Michelin Guide."""
        mapping = {
            "3": "3-stars-michelin",
            "2": "2-stars-michelin",
            "1": "1-star-michelin",
            "gourmand": "bib-gourmand",
            "selected": "the-plate-michelin",
            "all": "",  # No filter, all restaurants
        }
        return mapping.get(self.michelin_level.lower(), "3-stars-michelin")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
