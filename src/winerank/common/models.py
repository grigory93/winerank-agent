"""SQLAlchemy ORM models for Winerank database."""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    Enum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class CrawlStatus(str, PyEnum):
    """Restaurant crawl status enumeration."""

    PENDING = "pending"
    HAS_WEBSITE = "has_website"
    NO_WEBSITE = "no_website"
    WINE_LIST_FOUND = "wine_list_found"
    NO_WINE_LIST = "no_wine_list"
    DOWNLOAD_LIST_FAILED = "download_list_failed"
    ERROR = "error"


class JobStatus(str, PyEnum):
    """Job status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MichelinDistinction(str, PyEnum):
    """Michelin distinction levels."""

    THREE_STARS = "3-stars"
    TWO_STARS = "2-stars"
    ONE_STAR = "1-star"
    BIB_GOURMAND = "bib-gourmand"
    SELECTED = "selected"


class SiteOfRecord(Base):
    """Website of record used as starting point for crawling."""

    __tablename__ = "sites_of_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    site_url: Mapped[str] = mapped_column(Text, nullable=False)
    navigational_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_visited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    restaurants: Mapped[list["Restaurant"]] = relationship(
        back_populates="site_of_record", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="site_of_record", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SiteOfRecord(id={self.id}, name='{self.site_name}')>"


class Restaurant(Base):
    """Restaurant entity with crawl metadata."""

    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    michelin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wine_list_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Cached direct URL to wine list"
    )
    michelin_distinction: Mapped[Optional[str]] = mapped_column(
        Enum(MichelinDistinction, name="michelin_distinction_enum"), nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="USA")
    cuisine: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price_range: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    crawl_status: Mapped[str] = mapped_column(
        Enum(CrawlStatus, name="crawl_status_enum"),
        nullable=False,
        default=CrawlStatus.PENDING,
    )
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Crawl performance metrics
    crawl_duration_seconds: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Time taken to crawl this restaurant's website"
    )
    llm_tokens_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total LLM tokens used during crawl"
    )
    pages_visited: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of pages visited during crawl"
    )

    # Foreign keys
    site_of_record_id: Mapped[int] = mapped_column(
        ForeignKey("sites_of_record.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    site_of_record: Mapped["SiteOfRecord"] = relationship(back_populates="restaurants")
    wine_lists: Mapped[list["WineList"]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Restaurant(id={self.id}, name='{self.name}', status={self.crawl_status})>"


class WineList(Base):
    """Wine list downloaded from a restaurant."""

    __tablename__ = "wine_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Descriptive name for the wine list"
    )
    source_url: Mapped[str] = mapped_column(
        Text, nullable=False, comment="URL where wine list was downloaded from"
    )
    local_file_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Local path to downloaded file"
    )
    text_file_path: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Path to extracted text file"
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 hash of downloaded file"
    )
    wine_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of wines parsed from list"
    )
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Foreign keys
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    restaurant: Mapped["Restaurant"] = relationship(back_populates="wine_lists")
    wines: Mapped[list["Wine"]] = relationship(
        back_populates="wine_list", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WineList(id={self.id}, restaurant_id={self.restaurant_id}, wines={self.wine_count})>"


class Wine(Base):
    """Wine entry parsed from a wine list."""

    __tablename__ = "wines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    winery: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    varietal: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    wine_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="Red, White, Sparkling, etc."
    )
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vineyard: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vintage: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="Year or NV (non-vintage)"
    )
    format: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="Bottle, by the glass, magnum, etc."
    )
    price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Price in restaurant's currency"
    )
    note: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Additional information"
    )

    # Foreign keys
    wine_list_id: Mapped[int] = mapped_column(
        ForeignKey("wine_lists.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    wine_list: Mapped["WineList"] = relationship(back_populates="wines")

    def __repr__(self) -> str:
        return f"<Wine(id={self.id}, name='{self.name}', winery='{self.winery}', vintage='{self.vintage}')>"


class Job(Base):
    """Crawler job tracking and checkpointing."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="crawler", comment="Type of job: crawler, parser, ranker"
    )
    michelin_level: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="Michelin level filter for crawler jobs"
    )
    status: Mapped[str] = mapped_column(
        Enum(JobStatus, name="job_status_enum"),
        nullable=False,
        default=JobStatus.PENDING,
    )
    total_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total pages to process"
    )
    current_page: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current page being processed"
    )
    restaurants_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total restaurants discovered"
    )
    restaurants_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Restaurants fully processed"
    )
    wine_lists_downloaded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Wine lists successfully downloaded"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Job duration in seconds"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Foreign keys
    site_of_record_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sites_of_record.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    site_of_record: Mapped[Optional["SiteOfRecord"]] = relationship(
        back_populates="jobs"
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type='{self.job_type}', status={self.status}, progress={self.restaurants_processed}/{self.restaurants_found})>"
