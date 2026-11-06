"""Separate pseudonymous analytics consent journal; no account or contact fields."""

import sqlalchemy as sa
from alembic import op

revision = "0011_analytics_consent"
down_revision = "0010_notification_retry_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_consent_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("browser_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(8), nullable=False),
        sa.Column("text_version", sa.String(64), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_analytics_consent_events")),
        sa.CheckConstraint(
            "event_type IN ('grant', 'withdraw')",
            name=op.f("ck_analytics_consent_events_event_type"),
        ),
        sa.CheckConstraint(
            "text_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
            name=op.f("ck_analytics_consent_events_text_version"),
        ),
    )
    op.create_index(
        "ix_analytics_consent_events_recorded_at", "analytics_consent_events", ["recorded_at"]
    )


def downgrade() -> None:
    # Destructive by nature: never invoke against retained production journal without approval.
    op.drop_index("ix_analytics_consent_events_recorded_at", table_name="analytics_consent_events")
    op.drop_table("analytics_consent_events")
