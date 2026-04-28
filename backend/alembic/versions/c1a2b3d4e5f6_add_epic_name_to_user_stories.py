"""add_epic_name_to_user_stories

Revision ID: c1a2b3d4e5f6
Revises: beac5ba154b7
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'beac5ba154b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_stories', sa.Column('epic_name', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('user_stories', 'epic_name')
