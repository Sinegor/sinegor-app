"""Persist asynchronous Disk deletion operations for safe retries."""

import sqlalchemy as sa
from alembic import op

revision = "0007_disk_operations"
down_revision = "0006_agreements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "disk_folders",
        sa.Column("deletion_succeeded", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("disk_folders", sa.Column("deletion_operation_id", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("disk_folders", "deletion_operation_id")
    op.drop_column("disk_folders", "deletion_succeeded")
