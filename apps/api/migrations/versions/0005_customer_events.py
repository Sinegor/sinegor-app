"""Record customer card changes without retaining personal data in audit payloads."""

import sqlalchemy as sa
from alembic import op

revision = "0005_customer_events"
down_revision = "0004_reject_nan_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_events",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_admin_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_customer_events_event_type_format")
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_admin_id"], ["admin_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_events_customer_id_created_at",
        "customer_events",
        ["customer_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_events_customer_id_created_at", table_name="customer_events")
    op.drop_table("customer_events")
