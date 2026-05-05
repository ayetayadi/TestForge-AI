"""risk: add project_id, make test_plan_id optional

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-27 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add project_id column (nullable first to allow backfill)
    op.add_column('risks', sa.Column('project_id', sa.String(36), nullable=True))

    # 2. Backfill project_id from test_plan where possible
    op.execute("""
        UPDATE risks r
        SET project_id = tp.project_id
        FROM test_plans tp
        WHERE r.test_plan_id = tp.id
          AND r.project_id IS NULL
    """)

    # 3. Make project_id NOT NULL and add FK
    op.alter_column('risks', 'project_id', nullable=False)
    op.create_foreign_key(
        'fk_risks_project_id',
        'risks', 'jira_projects',
        ['project_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('idx_risk_project_id', 'risks', ['project_id'])

    # 4. Drop old CASCADE FK on test_plan_id, re-add as nullable SET NULL
    op.drop_constraint('risks_test_plan_id_fkey', 'risks', type_='foreignkey')
    op.alter_column('risks', 'test_plan_id', nullable=True)
    op.create_foreign_key(
        'fk_risks_test_plan_id',
        'risks', 'test_plans',
        ['test_plan_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_risks_test_plan_id', 'risks', type_='foreignkey')
    op.alter_column('risks', 'test_plan_id', nullable=False)
    op.create_foreign_key(
        'risks_test_plan_id_fkey',
        'risks', 'test_plans',
        ['test_plan_id'], ['id'],
        ondelete='CASCADE',
    )
    op.drop_index('idx_risk_project_id', table_name='risks')
    op.drop_constraint('fk_risks_project_id', 'risks', type_='foreignkey')
    op.drop_column('risks', 'project_id')
