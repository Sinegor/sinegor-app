"""Customer blocking and standardized security facts."""

import sqlalchemy as sa
from alembic import op

revision = "0013_customer_blocking"
down_revision = "0012_security_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("blocked_at", sa.DateTime(timezone=True)))
    op.add_column("customers", sa.Column("block_reason", sa.Text()))
    op.add_column("customers", sa.Column("block_comment", sa.Text()))
    op.add_column(
        "customers", sa.Column("access_revision", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_check_constraint(
        "block_details",
        "customers",
        "(blocked_at IS NULL AND block_reason IS NULL AND block_comment IS NULL) OR "
        "(blocked_at IS NOT NULL AND block_reason IS NOT NULL AND "
        "length(btrim(block_reason)) BETWEEN 1 AND 2000 AND "
        "(block_comment IS NULL OR length(block_comment) <= 2000))",
    )
    op.drop_constraint(
        op.f("ck_security_events_reason_code"), "security_events", type_="check", schema="public"
    )
    op.create_check_constraint(
        "reason_code",
        "security_events",
        "reason_code IN ('admin_login', 'magic_link_login', 'invalid_credentials', 'invalid_re"
        "quest', 'attempt_limit', 'authentication_required', 'admin_required', 'customer_requi"
        "red', 'order_not_owned', 'csrf_failed', 'session_created', 'session_rotated', 'logout"
        "', 'magic_link_issued', 'invitation_issued', 'link_replaced', 'link_consumed', 'deliv"
        "ery_failed', 'email_changed', 'admin_created', 'agreement_required', 'customer_blocke"
        "d', 'customer_unblocked')",
        schema="public",
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM public.security_events "
            "WHERE reason_code IN ('customer_blocked', 'customer_unblocked'))"
        )
    ):
        raise RuntimeError("Cannot downgrade while blocking security facts must be retained")
    op.drop_constraint(
        op.f("ck_security_events_reason_code"), "security_events", type_="check", schema="public"
    )
    op.create_check_constraint(
        "reason_code",
        "security_events",
        "reason_code IN ('admin_login', 'magic_link_login', 'invalid_credentials', 'invalid_re"
        "quest', 'attempt_limit', 'authentication_required', 'admin_required', 'customer_requi"
        "red', 'order_not_owned', 'csrf_failed', 'session_created', 'session_rotated', 'logout"
        "', 'magic_link_issued', 'invitation_issued', 'link_replaced', 'link_consumed', 'deliv"
        "ery_failed', 'email_changed', 'admin_created', 'agreement_required')",
        schema="public",
    )
    op.drop_constraint(op.f("ck_customers_block_details"), "customers", type_="check")
    for column in ("access_revision", "block_comment", "block_reason", "blocked_at"):
        op.drop_column("customers", column)
