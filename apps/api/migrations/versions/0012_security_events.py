"""Separate append-only security journal and bounded privileged retention operation."""

import sqlalchemy as sa
from alembic import op

revision = "0012_security_events"
down_revision = "0011_analytics_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.statement_timestamp(),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("result", sa.String(7), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("user_role", sa.String(8), nullable=True),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "event_type IN ('authentication', 'rate_limit', 'access_denied', "
            "'credential_issued', 'credential_revoked', 'privilege_changed')",
            name="event_type",
        ),
        sa.CheckConstraint("result IN ('success', 'failure')", name="result"),
        sa.CheckConstraint(
            "reason_code IN ('admin_login', 'magic_link_login', 'invalid_credentials', "
            "'invalid_request', 'attempt_limit', 'authentication_required', 'admin_required', "
            "'customer_required', 'order_not_owned', 'csrf_failed', 'session_created', "
            "'session_rotated', 'logout', 'magic_link_issued', 'invitation_issued', "
            "'link_replaced', 'link_consumed', 'delivery_failed', "
            "'email_changed', 'admin_created', 'agreement_required')",
            name="reason_code",
        ),
        sa.CheckConstraint("request_id ~ '^[0-9a-f]{32}$'", name="request_id"),
        sa.CheckConstraint(
            "user_role IS NULL OR user_role IN ('admin', 'customer')", name="user_role"
        ),
        sa.CheckConstraint("(user_id IS NULL) = (user_role IS NULL)", name="known_user"),
    )
    op.create_index("ix_security_events_recorded_at", "security_events", ["recorded_at"])
    op.create_index(
        "ix_security_events_event_type_recorded_at",
        "security_events",
        ["event_type", "recorded_at"],
    )
    op.execute("REVOKE ALL ON TABLE public.security_events FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION public.purge_security_events() RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        SET TimeZone = 'UTC'
        SET sinegor.security_retention_days = '90'
        AS $$
        DECLARE removed bigint;
        BEGIN
            DELETE FROM public.security_events
            WHERE recorded_at < (
                date_trunc('day', statement_timestamp()) -
                make_interval(days => current_setting('sinegor.security_retention_days')::integer)
            );
            GET DIAGNOSTICS removed = ROW_COUNT;
            RETURN removed;
        END;
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.purge_security_events() FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.purge_security_events()")
    op.drop_table("security_events")
