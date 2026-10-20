"""B2 domain models

Revision ID: 0002_domain_models
Revises: 0001_backend_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_domain_models"
down_revision: str | Sequence[str] | None = "0001_backend_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(password_hash) <> ''", name=op.f("ck_admin_users_password_hash_present")
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND email !~ '[[:space:]]'",
            name=op.f("ck_admin_users_normalized_email"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        sa.UniqueConstraint("email", name=op.f("uq_admin_users_email")),
    )
    op.create_table(
        "customers",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND email !~ '[[:space:]]'",
            name=op.f("ck_customers_normalized_email"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("email", name=op.f("uq_customers_email")),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "invitation",
                "magic_link",
                name="token_purpose",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_tokens_token_hash_sha256")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_tokens_positive_lifetime")
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR (used_at >= created_at AND used_at <= expires_at)",
            name=op.f("ck_auth_tokens_used_during_lifetime"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_auth_tokens_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_auth_tokens_customer_id"), "auth_tokens", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_auth_tokens_expires_at"), "auth_tokens", ["expires_at"], unique=False)
    op.create_table(
        "orders",
        sa.Column("number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "service_type",
            sa.Enum(
                "analysis",
                "technical_preparation",
                name="service_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agreed_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "awaiting_agreement",
                "awaiting_materials",
                "in_progress",
                "result_ready",
                "completed",
                "cancelled",
                name="order_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="awaiting_agreement",
            nullable=False,
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'cancelled')) = (closed_at IS NOT NULL)",
            name=op.f("ck_orders_closed_status"),
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR closed_at >= result_notified_at",
            name=op.f("ck_orders_completion_time"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('result_ready', 'completed') OR (ready_at IS NOT NULL AND "
            "result_notified_at IS NOT NULL)",
            name=op.f("ck_orders_ready_evidence"),
        ),
        sa.CheckConstraint(
            "agreed_price IS NULL OR agreed_price >= 0", name=op.f("ck_orders_nonnegative_price")
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at", name=op.f("ck_orders_closed_time")
        ),
        sa.CheckConstraint(
            "ready_at IS NULL OR ready_at >= created_at", name=op.f("ck_orders_ready_time")
        ),
        sa.CheckConstraint(
            "result_notified_at IS NULL OR (ready_at IS NOT NULL AND result_notified_at >= "
            "ready_at)",
            name=op.f("ck_orders_notification_time"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("number", name=op.f("uq_orders_number")),
    )
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)
    op.create_index("ix_orders_status_ready_at", "orders", ["status", "ready_at"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "session_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_session_hash_sha256")
        ),
        sa.CheckConstraint(
            "(customer_id IS NULL) <> (admin_id IS NULL)",
            name=op.f("ck_sessions_exactly_one_principal"),
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_sessions_positive_lifetime")),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_sessions_revocation_time"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name=op.f("fk_sessions_admin_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_sessions_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("session_hash", name=op.f("uq_sessions_session_hash")),
    )
    op.create_index(op.f("ix_sessions_admin_id"), "sessions", ["admin_id"], unique=False)
    op.create_index(op.f("ix_sessions_customer_id"), "sessions", ["customer_id"], unique=False)
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_table(
        "agreements",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "awaiting_customer",
                "under_review",
                "approved",
                "rejected",
                name="agreement_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="awaiting_customer",
            nullable=False,
        ),
        sa.Column("initial_pdf_key", sa.Text(), nullable=True),
        sa.Column("returned_pdf_key", sa.Text(), nullable=True),
        sa.Column("final_pdf_key", sa.Text(), nullable=True),
        sa.Column("final_sha256", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "final_sha256 IS NULL OR final_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_agreements_final_sha256_format"),
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR (nullif(btrim(final_pdf_key), '') IS NOT NULL AND "
            "final_sha256 IS NOT NULL AND verified_at IS NOT NULL AND verified_by_id IS NOT"
            " NULL)",
            name=op.f("ck_agreements_approved_evidence"),
        ),
        sa.CheckConstraint(
            "verified_at IS NULL OR verified_at >= created_at",
            name=op.f("ck_agreements_verification_time"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_agreements_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_id"],
            ["admin_users.id"],
            name=op.f("fk_agreements_verified_by_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agreements")),
        sa.UniqueConstraint("order_id", name=op.f("uq_agreements_order_id")),
    )
    op.create_table(
        "deletion_requests",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "retention_expired",
                "early_permission",
                name="deletion_reason",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "waiting",
                "deferred",
                "confirmed",
                "performed",
                "error",
                name="deletion_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="waiting",
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("early_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'performed') = (performed_at IS NOT NULL)",
            name=op.f("ck_deletion_requests_performed_status"),
        ),
        sa.CheckConstraint(
            "reason <> 'early_permission' OR early_authorized_at IS NOT NULL",
            name=op.f("ck_deletion_requests_early_permission"),
        ),
        sa.CheckConstraint(
            "status <> 'deferred' OR (deferred_until IS NOT NULL AND "
            "nullif(btrim(admin_note), '') IS NOT NULL)",
            name=op.f("ck_deletion_requests_deferral_evidence"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('confirmed', 'performed', 'error') OR (confirmed_at IS NOT NULL"
            " AND confirmed_by_id IS NOT NULL)",
            name=op.f("ck_deletion_requests_admin_confirmation"),
        ),
        sa.CheckConstraint(
            "performed_at IS NULL OR (confirmed_at IS NOT NULL AND performed_at >= confirmed_at)",
            name=op.f("ck_deletion_requests_performed_time"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_id"],
            ["admin_users.id"],
            name=op.f("fk_deletion_requests_confirmed_by_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_deletion_requests_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_requests")),
        sa.UniqueConstraint("order_id", name=op.f("uq_deletion_requests_order_id")),
    )
    op.create_index(
        "ix_deletion_requests_status_due_at",
        "deletion_requests",
        ["status", "due_at"],
        unique=False,
    )
    op.create_table(
        "disk_folders",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("disk_path", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("folder_url", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "disk_path LIKE 'disk:/%' AND length(disk_path) > 6",
            name=op.f("ck_disk_folders_disk_path_format"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_disk_folders_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disk_folders")),
        sa.UniqueConstraint("disk_path", name=op.f("uq_disk_folders_disk_path")),
        sa.UniqueConstraint("order_id", name=op.f("uq_disk_folders_order_id")),
        sa.UniqueConstraint("resource_id", name=op.f("uq_disk_folders_resource_id")),
    )
    op.create_table(
        "material_handovers",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_material_handovers_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_material_handovers")),
        sa.UniqueConstraint("order_id", name=op.f("uq_material_handovers_order_id")),
    )
    op.create_table(
        "order_events",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_customer_id", sa.Uuid(), nullable=True),
        sa.Column("actor_admin_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_order_events_event_type_format")
        ),
        sa.CheckConstraint(
            "actor_customer_id IS NULL OR actor_admin_id IS NULL",
            name=op.f("ck_order_events_at_most_one_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            name=op.f("fk_order_events_actor_admin_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_customer_id"],
            ["customers.id"],
            name=op.f("fk_order_events_actor_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_events_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_events")),
    )
    op.create_index(
        "ix_order_events_order_id_created_at",
        "order_events",
        ["order_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "payment_records",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "unpaid", "paid", name="payment_status", native_enum=False, create_constraint=True
            ),
            server_default="unpaid",
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'paid' OR (confirmed_at IS NOT NULL AND confirmed_by_id IS NOT NULL)",
            name=op.f("ck_payment_records_paid_confirmation"),
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at",
            name=op.f("ck_payment_records_confirmation_time"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_id"],
            ["admin_users.id"],
            name=op.f("fk_payment_records_confirmed_by_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payment_records_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_records")),
        sa.UniqueConstraint("order_id", name=op.f("uq_payment_records_order_id")),
    )


def downgrade() -> None:
    op.drop_table("payment_records")
    op.drop_index("ix_order_events_order_id_created_at", table_name="order_events")
    op.drop_table("order_events")
    op.drop_table("material_handovers")
    op.drop_table("disk_folders")
    op.drop_index("ix_deletion_requests_status_due_at", table_name="deletion_requests")
    op.drop_table("deletion_requests")
    op.drop_table("agreements")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_customer_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_admin_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_orders_status_ready_at", table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_auth_tokens_expires_at"), table_name="auth_tokens")
    op.drop_index(op.f("ix_auth_tokens_customer_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("customers")
    op.drop_table("admin_users")
