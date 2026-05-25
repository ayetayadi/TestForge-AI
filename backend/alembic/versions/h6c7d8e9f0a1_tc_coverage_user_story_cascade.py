"""tc_coverage user_story_id: SET NULL → CASCADE, NOT NULL

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-05-20 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "h6c7d8e9f0a1"
down_revision = "g5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove orphaned rows (user_story_id IS NULL from previous SET NULL behavior)
    op.execute("DELETE FROM tc_coverages WHERE user_story_id IS NULL")

    # 2. Drop old FK constraint (SET NULL)
    op.drop_constraint("tc_coverages_user_story_id_fkey", "tc_coverages", type_="foreignkey")

    # 3. Make column NOT NULL
    op.alter_column("tc_coverages", "user_story_id", nullable=False)

    # 4. Re-create FK with CASCADE
    op.create_foreign_key(
        "tc_coverages_user_story_id_fkey",
        "tc_coverages",
        "user_stories",
        ["user_story_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("tc_coverages_user_story_id_fkey", "tc_coverages", type_="foreignkey")
    op.alter_column("tc_coverages", "user_story_id", nullable=True)
    op.create_foreign_key(
        "tc_coverages_user_story_id_fkey",
        "tc_coverages",
        "user_stories",
        ["user_story_id"],
        ["id"],
        ondelete="SET NULL",
    )
