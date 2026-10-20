"""Versioned PDF exchange and durable cleanup of obsolete agreement files."""

import sqlalchemy as sa
from alembic import op

revision = "0006_agreements"
down_revision = "0005_customer_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agreements", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("agreements", sa.Column("initial_sha256", sa.String(64), nullable=True))
    op.add_column("agreements", sa.Column("returned_sha256", sa.String(64), nullable=True))
    op.add_column("agreements", sa.Column("rejection_reason", sa.String(2000), nullable=True))
    for name, condition in (
        ("positive_revision", "revision > 0"),
        ("initial_sha256_format", "initial_sha256 IS NULL OR initial_sha256 ~ '^[0-9a-f]{64}$'"),
        ("returned_sha256_format", "returned_sha256 IS NULL OR returned_sha256 ~ '^[0-9a-f]{64}$'"),
    ):
        op.create_check_constraint(op.f(f"ck_agreements_{name}"), "agreements", condition)
    op.create_table(
        "agreement_file_deletions",
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_key"),
    )
    op.create_index(
        "ix_agreement_file_deletions_order_id", "agreement_file_deletions", ["order_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agreement_file_deletions_order_id", table_name="agreement_file_deletions")
    op.drop_table("agreement_file_deletions")
    for name in ("returned_sha256_format", "initial_sha256_format", "positive_revision"):
        op.drop_constraint(op.f(f"ck_agreements_{name}"), "agreements", type_="check")
    for column in ("rejection_reason", "returned_sha256", "initial_sha256", "revision"):
        op.drop_column("agreements", column)
