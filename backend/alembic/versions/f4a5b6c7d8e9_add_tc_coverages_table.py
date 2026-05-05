"""add tc_coverages table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tc_coverages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('test_plan_id', sa.String(36), sa.ForeignKey('test_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_story_id', sa.String(36), sa.ForeignKey('user_stories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('issue_key', sa.String(50), nullable=True),
        sa.Column('user_story_title', sa.String(500), nullable=True),
        sa.Column('scenario_type', sa.String(20), nullable=False),
        sa.Column('coverage_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('covered_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_ac_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tc_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('test_plan_id', 'user_story_id', 'scenario_type', name='uq_tc_coverage'),
    )
    op.create_index('idx_tc_coverage_plan', 'tc_coverages', ['test_plan_id'])
    op.create_index('idx_tc_coverage_us', 'tc_coverages', ['user_story_id'])


def downgrade() -> None:
    op.drop_index('idx_tc_coverage_us', table_name='tc_coverages')
    op.drop_index('idx_tc_coverage_plan', table_name='tc_coverages')
    op.drop_table('tc_coverages')
