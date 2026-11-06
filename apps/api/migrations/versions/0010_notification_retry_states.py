"""Add stopped delivery states without changing or deleting existing outbox data."""

from alembic import op

revision = "0010_notification_retry_states"
down_revision = "0009_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_status"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_status"),
        "notifications",
        "status IN ('pending','processing','sent','cancelled','failed','expired')",
    )


def downgrade() -> None:
    # Refuse a lossy downgrade instead of resurrecting stopped deliveries or deleting data.
    op.create_check_constraint(
        "ck_notifications_downgrade_states",
        "notifications",
        "status IN ('pending','processing','sent','cancelled')",
    )
    op.drop_constraint(op.f("ck_notifications_status"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_status"),
        "notifications",
        "status IN ('pending','processing','sent','cancelled')",
    )
    op.drop_constraint("ck_notifications_downgrade_states", "notifications", type_="check")
