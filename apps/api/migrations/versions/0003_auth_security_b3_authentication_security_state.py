"""B3 authentication security state

Revision ID: 0003_auth_security
Revises: 0002_domain_models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_auth_security"
down_revision: str | Sequence[str] | None = "0002_domain_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "key_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_rate_limits_key_hash_sha256")
        ),
        sa.CheckConstraint("attempts > 0", name=op.f("ck_auth_rate_limits_positive_attempts")),
        sa.PrimaryKeyConstraint("key_hash", name=op.f("pk_auth_rate_limits")),
    )
    op.create_index(
        op.f("ix_auth_rate_limits_window_started_at"),
        "auth_rate_limits",
        ["window_started_at"],
        unique=False,
    )
    op.add_column("admin_users", sa.Column("last_totp_step", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_admin_users_totp_step_nonnegative"),
        "admin_users",
        "last_totp_step IS NULL OR last_totp_step >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_admin_users_totp_step_nonnegative"), "admin_users", type_="check")
    op.drop_column("admin_users", "last_totp_step")
    op.drop_index(op.f("ix_auth_rate_limits_window_started_at"), table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
