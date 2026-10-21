"""Durable email and Telegram delivery without additional infrastructure."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_notifications"
down_revision = "0008_disk_deletion_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("recipient", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(32), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','processing','sent','cancelled')",
            name=op.f("ck_notifications_status"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_notifications_attempts")),
        sa.CheckConstraint(
            "(status = 'processing') = (lease_id IS NOT NULL AND lease_until IS NOT NULL)",
            name=op.f("ck_notifications_lease"),
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    op.create_index(
        "ix_notifications_status_available_at", "notifications", ["status", "available_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_status_available_at", table_name="notifications")
    op.drop_table("notifications")
