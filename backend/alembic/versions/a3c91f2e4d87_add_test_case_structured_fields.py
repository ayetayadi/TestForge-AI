"""add_test_case_structured_fields

Revision ID: a3c91f2e4d87
Revises: 9f1ba0651782
Create Date: 2026-04-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a3c91f2e4d87'
down_revision: Union[str, Sequence[str], None] = '9f1ba0651782'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('test_cases', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('test_cases', sa.Column('priority', sa.String(length=20), nullable=True))
    op.add_column('test_cases', sa.Column(
        'preconditions',
        postgresql.JSONB(astext_type=sa.Text()),
        server_default='[]',
        nullable=False
    ))
    op.add_column('test_cases', sa.Column(
        'postconditions',
        postgresql.JSONB(astext_type=sa.Text()),
        server_default='[]',
        nullable=False
    ))
    op.add_column('test_cases', sa.Column(
        'steps',
        postgresql.JSONB(astext_type=sa.Text()),
        server_default='[]',
        nullable=False
    ))


def downgrade() -> None:
    op.drop_column('test_cases', 'steps')
    op.drop_column('test_cases', 'postconditions')
    op.drop_column('test_cases', 'preconditions')
    op.drop_column('test_cases', 'priority')
    op.drop_column('test_cases', 'description')
