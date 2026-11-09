"""Cancellation reasons and cancellation as a manual deletion basis."""

import sqlalchemy as sa
from alembic import op

revision = "0014_order_cancellation"
down_revision = "0013_customer_blocking"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("cancellation_internal_reason", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("cancellation_customer_reason", sa.Text(), nullable=True))
    op.drop_constraint(
        op.f("ck_deletion_requests_deletion_reason"), "deletion_requests", type_="check"
    )
    op.create_check_constraint(
        "deletion_reason",
        "deletion_requests",
        "reason IN ('retention_expired', 'early_permission', 'order_cancelled')",
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM orders WHERE cancellation_internal_reason IS NOT NULL "
            "OR cancellation_customer_reason IS NOT NULL) OR EXISTS "
            "(SELECT 1 FROM deletion_requests WHERE reason = 'order_cancelled')"
        )
    ):
        raise RuntimeError("Cannot downgrade while cancellation decisions must be retained")
    op.drop_constraint(
        op.f("ck_deletion_requests_deletion_reason"), "deletion_requests", type_="check"
    )
    op.create_check_constraint(
        "deletion_reason",
        "deletion_requests",
        "reason IN ('retention_expired', 'early_permission')",
    )
    op.drop_column("orders", "cancellation_customer_reason")
    op.drop_column("orders", "cancellation_internal_reason")
