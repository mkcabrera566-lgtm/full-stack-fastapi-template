"""Add tickets without altering existing tables.

Revision ID: a7b8c9d0e1f2
Revises: fe56fa70289e
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=10000), nullable=False),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "medium",
                "high",
                "urgent",
                name="ticket_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "in_progress",
                "resolved",
                "closed",
                name="ticket_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["user.id"], name="ticket_owner_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_owner_id", "ticket", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_owner_id", table_name="ticket")
    op.drop_table("ticket")
