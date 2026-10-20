"""Reject NaN in agreed order prices.

Revision ID: 0004_reject_nan_price
Revises: 0003_auth_security
"""

from alembic import op

revision = "0004_reject_nan_price"
down_revision = "0003_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_orders_nonnegative_price"), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_nonnegative_price"),
        "orders",
        "agreed_price IS NULL OR (agreed_price >= 0 AND agreed_price <> 'NaN'::numeric)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_orders_nonnegative_price"), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_nonnegative_price"), "orders", "agreed_price IS NULL OR agreed_price >= 0"
    )
