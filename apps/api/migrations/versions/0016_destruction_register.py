"""Independent destruction register; no foreign keys to the deleted business graph."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_destruction_register"
down_revision = "0015_business_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "destruction_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("destroyed_at", sa.DateTime(timezone=True)),
        sa.Column("bundle_key", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint(
            "kind IN ('disk_folder','consultation_auto','consultation_manual','security_events',"
            "'customer_fields','agreement','order_history','customer')",
            name="kind",
        ),
        sa.CheckConstraint(
            "state IN ('preparing','executing','verifying','error','uncertain',"
            "'documents_pending','ready')",
            name="state",
        ),
        sa.CheckConstraint("(destroyed_at IS NULL) = (expires_at IS NULL)", name="confirmation"),
        sa.CheckConstraint(
            "state NOT IN ('documents_pending','ready') OR destroyed_at IS NOT NULL",
            name="confirmed_state",
        ),
        sa.CheckConstraint("state <> 'ready' OR bundle_key IS NOT NULL", name="ready_bundle"),
    )
    op.create_index(
        "ix_destruction_operations_created_at", "destruction_operations", ["created_at", "id"]
    )
    op.create_index(
        "ix_destruction_operations_expires_at", "destruction_operations", ["expires_at"]
    )
    op.add_column("retention_file_deletions", sa.Column("operation_id", sa.Uuid()))
    op.create_index(
        "ix_retention_file_deletions_operation_id", "retention_file_deletions", ["operation_id"]
    )
    op.execute("""
        CREATE FUNCTION public.keep_destruction_evidence() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF OLD.destroyed_at IS NOT NULL AND (
                NEW.metadata_json IS DISTINCT FROM OLD.metadata_json OR
                NEW.kind IS DISTINCT FROM OLD.kind OR
                NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
                NEW.destroyed_at IS DISTINCT FROM OLD.destroyed_at OR
                NEW.expires_at IS DISTINCT FROM OLD.expires_at
            ) THEN
                RAISE EXCEPTION 'Confirmed destruction evidence is immutable' USING ERRCODE='23514';
            END IF;
            IF OLD.bundle_key IS NOT NULL AND NEW.bundle_key IS DISTINCT FROM OLD.bundle_key THEN
                RAISE EXCEPTION 'Document bundle is immutable' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER keep_destruction_evidence BEFORE UPDATE ON public.destruction_operations
        FOR EACH ROW EXECUTE FUNCTION public.keep_destruction_evidence();
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM destruction_operations)")):
        raise RuntimeError("Cannot discard destruction evidence")
    op.execute("DROP TRIGGER keep_destruction_evidence ON public.destruction_operations")
    op.execute("DROP FUNCTION public.keep_destruction_evidence()")
    op.drop_column("retention_file_deletions", "operation_id")
    op.drop_table("destruction_operations")
