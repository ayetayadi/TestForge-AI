"""add workflow_note to user_story_versions

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-05-21 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'h6c7d8e9f0a1'
down_revision = 'g5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_story_versions',
        sa.Column('workflow_note', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('user_story_versions', 'workflow_note')
