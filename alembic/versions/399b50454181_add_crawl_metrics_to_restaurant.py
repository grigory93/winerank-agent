"""Add crawl metrics to Restaurant

Revision ID: 399b50454181
Revises: 1cff6e8d6528
Create Date: 2026-02-15 08:06:11.486771

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '399b50454181'
down_revision = '1cff6e8d6528'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: checkpoint_* tables are managed by LangGraph, not our ORM.
    # They must NOT be dropped by Alembic.
    op.add_column('restaurants', sa.Column('crawl_duration_seconds', sa.Numeric(precision=10, scale=2), nullable=True, comment="Time taken to crawl this restaurant's website"))
    op.add_column('restaurants', sa.Column('llm_tokens_used', sa.Integer(), nullable=False, server_default='0', comment='Total LLM tokens used during crawl'))
    op.add_column('restaurants', sa.Column('pages_visited', sa.Integer(), nullable=False, server_default='0', comment='Number of pages visited during crawl'))
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_column('restaurants', 'pages_visited')
    op.drop_column('restaurants', 'llm_tokens_used')
    op.drop_column('restaurants', 'crawl_duration_seconds')
    # NOTE: checkpoint_* tables are managed by LangGraph – do not touch them.
