"""add is_closed to test_executions

Revision ID: j8e9f0a1b2c3
Revises: i7d8e9f0a1b2
Create Date: 2026-05-29 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "j8e9f0a1b2c3"
down_revision = "i7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_executions",
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "test_executions",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "test_executions",
        sa.Column(
            "closed_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("test_executions", "closed_by")
    op.drop_column("test_executions", "closed_at")
    op.drop_column("test_executions", "is_closed")
