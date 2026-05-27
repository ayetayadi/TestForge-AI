"""add estimated_duration to test_cases

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-05-26 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'h6c7d8e9f0a1'
down_revision = ('g5b6c7d8e9f0', 'ac79303ad538')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('test_cases', sa.Column('estimated_duration', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('test_cases', 'estimated_duration')
