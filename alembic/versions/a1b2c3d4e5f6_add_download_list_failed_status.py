"""Add download_list_failed to crawl_status_enum

Revision ID: a1b2c3d4e5f6
Revises: 399b50454181
Create Date: 2026-02-15 15:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '399b50454181'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    # Commit the current transaction so the statement can execute.
    op.execute("COMMIT")
    op.execute("ALTER TYPE crawl_status_enum ADD VALUE IF NOT EXISTS 'download_list_failed'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum type.
    # The value will remain but is harmless if unused.
    pass
