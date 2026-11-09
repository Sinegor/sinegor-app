"""Reliable fulfillment clock and a durable queue for expired private PDFs."""

import sqlalchemy as sa
from alembic import op

revision = "0015_business_retention"
down_revision = "0014_order_cancellation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_orders_fulfilled_at", "orders", ["fulfilled_at"])
    # The existing transition sets result_notified_at only after SMTP acceptance.
    # Require both administrative transition events as corroborating evidence.
    # Missing evidence stays NULL: no invented clock and no deletion during migration.
    op.execute("""
        UPDATE orders o SET fulfilled_at = o.result_notified_at
        WHERE o.result_notified_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM order_events e WHERE e.order_id = o.id
            AND e.event_type = 'status_result_ready' AND e.actor_admin_id IS NOT NULL
        ) AND EXISTS (
            SELECT 1 FROM order_events e WHERE e.order_id = o.id
            AND e.event_type = 'result_notification_sent' AND e.actor_admin_id IS NOT NULL
        )
    """)
    op.execute("""
        CREATE FUNCTION public.keep_order_fulfillment_time() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF OLD.fulfilled_at IS NOT NULL AND
               NEW.fulfilled_at IS DISTINCT FROM OLD.fulfilled_at THEN
                RAISE EXCEPTION 'Fulfillment timestamp is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.status = 'cancelled' AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
                RAISE EXCEPTION 'Cancellation timestamp is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""CREATE TRIGGER keep_order_fulfillment_time BEFORE UPDATE ON orders
        FOR EACH ROW EXECUTE FUNCTION public.keep_order_fulfillment_time()""")
    op.create_table(
        "retention_file_deletions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_key"),
    )

    op.create_index(
        "ix_retention_file_deletions_attempt",
        "retention_file_deletions",
        ["last_attempted_at", "id"],
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM retention_file_deletions) OR EXISTS "
            "(SELECT 1 FROM orders WHERE fulfilled_at IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard pending PDF deletion intents")
    op.drop_table("retention_file_deletions")
    op.execute("DROP TRIGGER keep_order_fulfillment_time ON orders")
    op.execute("DROP FUNCTION public.keep_order_fulfillment_time()")
    op.drop_index("ix_orders_fulfilled_at", table_name="orders")
    op.drop_column("orders", "fulfilled_at")
