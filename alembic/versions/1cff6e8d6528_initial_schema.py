"""Initial schema

Revision ID: 1cff6e8d6528
Revises:
Create Date: 2026-02-13 17:43:00.513513

Single consolidated schema for dev. All tables and columns in one revision.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1cff6e8d6528"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum values match winerank.common.models (CrawlStatus, JobStatus, MichelinDistinction)
    crawl_status_enum = sa.Enum(
        "pending",
        "has_website",
        "no_website",
        "wine_list_found",
        "no_wine_list",
        "download_list_failed",
        "error",
        name="crawl_status_enum",
    )
    job_status_enum = sa.Enum(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        name="job_status_enum",
    )
    michelin_distinction_enum = sa.Enum(
        "3-stars",
        "2-stars",
        "1-star",
        "bib-gourmand",
        "selected",
        name="michelin_distinction_enum",
    )
    op.create_table(
        "sites_of_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_name", sa.String(length=255), nullable=False),
        sa.Column("site_url", sa.Text(), nullable=False),
        sa.Column("navigational_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_visited_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_name"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "job_type",
            sa.String(length=50),
            nullable=False,
            comment="Type of job: crawler, parser, ranker",
        ),
        sa.Column(
            "michelin_level",
            sa.String(length=20),
            nullable=True,
            comment="Michelin level filter for crawler jobs",
        ),
        sa.Column(
            "status",
            job_status_enum,
            nullable=False,
        ),
        sa.Column(
            "total_pages",
            sa.Integer(),
            nullable=False,
            comment="Total pages to process",
        ),
        sa.Column(
            "current_page",
            sa.Integer(),
            nullable=False,
            comment="Current page being processed",
        ),
        sa.Column(
            "restaurants_found",
            sa.Integer(),
            nullable=False,
            comment="Total restaurants discovered",
        ),
        sa.Column(
            "restaurants_processed",
            sa.Integer(),
            nullable=False,
            comment="Restaurants fully processed",
        ),
        sa.Column(
            "wine_lists_downloaded",
            sa.Integer(),
            nullable=False,
            comment="Wine lists successfully downloaded",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "duration_seconds",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment="Job duration in seconds",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("site_of_record_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["site_of_record_id"], ["sites_of_record.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("michelin_url", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column(
            "wine_list_url",
            sa.Text(),
            nullable=True,
            comment="Cached direct URL to wine list",
        ),
        sa.Column(
            "michelin_distinction",
            michelin_distinction_enum,
            nullable=True,
        ),
        sa.Column(
            "address",
            sa.String(length=255),
            nullable=True,
            comment="Street address (number + street name)",
        ),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column(
            "zip_code",
            sa.String(length=20),
            nullable=True,
            comment="Postal / ZIP code",
        ),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("cuisine", sa.String(length=100), nullable=True),
        sa.Column("price_range", sa.String(length=20), nullable=True),
        sa.Column(
            "crawl_status",
            crawl_status_enum,
            nullable=False,
        ),
        sa.Column(
            "crawl_duration_seconds",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment="Time taken to crawl this restaurant's website",
        ),
        sa.Column(
            "llm_tokens_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total LLM tokens used during crawl",
        ),
        sa.Column(
            "pages_visited",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of pages visited during crawl",
        ),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("site_of_record_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_of_record_id"], ["sites_of_record.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wine_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "list_name",
            sa.String(length=255),
            nullable=True,
            comment="Descriptive name for the wine list",
        ),
        sa.Column(
            "source_url",
            sa.Text(),
            nullable=False,
            comment="URL where wine list was downloaded from",
        ),
        sa.Column(
            "local_file_path",
            sa.Text(),
            nullable=False,
            comment="Local path to downloaded file",
        ),
        sa.Column(
            "text_file_path",
            sa.Text(),
            nullable=True,
            comment="Path to extracted text file",
        ),
        sa.Column(
            "file_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 hash of downloaded file",
        ),
        sa.Column(
            "wine_count",
            sa.Integer(),
            nullable=False,
            comment="Number of wines parsed from list",
        ),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("winery", sa.String(length=255), nullable=True),
        sa.Column("varietal", sa.String(length=100), nullable=True),
        sa.Column(
            "wine_type",
            sa.String(length=50),
            nullable=True,
            comment="Red, White, Sparkling, etc.",
        ),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("vineyard", sa.String(length=255), nullable=True),
        sa.Column(
            "vintage",
            sa.String(length=20),
            nullable=True,
            comment="Year or NV (non-vintage)",
        ),
        sa.Column(
            "format",
            sa.String(length=50),
            nullable=True,
            comment="Bottle, by the glass, magnum, etc.",
        ),
        sa.Column(
            "price",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment="Price in restaurant's currency",
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
            comment="Additional information",
        ),
        sa.Column("wine_list_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["wine_list_id"], ["wine_lists.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("wines")
    op.drop_table("wine_lists")
    op.drop_table("restaurants")
    op.drop_table("jobs")
    op.drop_table("sites_of_record")
    sa.Enum(name="crawl_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="job_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="michelin_distinction_enum").drop(op.get_bind(), checkfirst=True)
