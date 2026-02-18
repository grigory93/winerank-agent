"""Add address and zip_code to Restaurant

Revision ID: b3e1f9a72c04
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3e1f9a72c04'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'restaurants',
        sa.Column(
            'address',
            sa.String(255),
            nullable=True,
            comment='Street address (number + street name)',
        ),
    )
    op.add_column(
        'restaurants',
        sa.Column(
            'zip_code',
            sa.String(20),
            nullable=True,
            comment='Postal / ZIP code',
        ),
    )


def downgrade() -> None:
    op.drop_column('restaurants', 'zip_code')
    op.drop_column('restaurants', 'address')
