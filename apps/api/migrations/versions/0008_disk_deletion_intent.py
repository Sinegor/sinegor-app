"""Persist deletion intent before calling Disk to reconcile lost responses."""

import sqlalchemy as sa
from alembic import op

revision = "0008_disk_deletion_intent"
down_revision = "0007_disk_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "disk_folders", sa.Column("deletion_started_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Preserve attempts already recorded by B6 before this column existed.
    op.execute("""
        UPDATE disk_folders AS folder
        SET deletion_started_at = (
            SELECT min(event.created_at)
            FROM order_events AS event
            WHERE event.order_id = folder.order_id
              AND event.event_type IN ('disk_deletion_started', 'disk_deletion_failed')
        )
    """)


def downgrade() -> None:
    op.drop_column("disk_folders", "deletion_started_at")
