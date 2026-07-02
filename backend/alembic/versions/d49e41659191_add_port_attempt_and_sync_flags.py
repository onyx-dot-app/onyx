"""add port_attempt and sync flags

Revision ID: d49e41659191
Revises: 81c4872d9666
Create Date: 2026-06-02 15:44:59.857241

Reindexing port, phase 1 (additive): port_attempt table (incl. up_to_doc_id) +
index_attempt.is_synthetic_seed + document.secondary_only_sync_pending.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d49e41659191"
down_revision = "81c4872d9666"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cc_pair_id", sa.Integer(), nullable=False),
        sa.Column("search_settings_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                "CANCELED",
                name="portattemptstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("last_processed_doc_id", sa.String(), nullable=True),
        sa.Column("up_to_doc_id", sa.String(), nullable=True),
        sa.Column("docs_ported", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_progress_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("time_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("time_completed", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["cc_pair_id"], ["connector_credential_pair.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["search_settings_id"], ["search_settings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # one active attempt per (cc_pair, FUTURE); predicate is uppercase (stored name)
    op.create_index(
        "ix_port_attempt_active_unique",
        "port_attempt",
        ["cc_pair_id", "search_settings_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('NOT_STARTED', 'IN_PROGRESS')"),
    )
    op.create_index(
        op.f("ix_port_attempt_cc_pair_id"), "port_attempt", ["cc_pair_id"], unique=False
    )
    op.create_index(
        op.f("ix_port_attempt_search_settings_id"),
        "port_attempt",
        ["search_settings_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_port_attempt_status"), "port_attempt", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_port_attempt_time_created"),
        "port_attempt",
        ["time_created"],
        unique=False,
    )

    op.add_column(
        "index_attempt",
        sa.Column(
            "is_synthetic_seed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    op.add_column(
        "document",
        sa.Column(
            "secondary_only_sync_pending",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_secondary_only_sync_pending",
        "document",
        ["id"],
        unique=False,
        postgresql_where=sa.text("secondary_only_sync_pending IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_secondary_only_sync_pending",
        table_name="document",
        postgresql_where=sa.text("secondary_only_sync_pending IS TRUE"),
    )
    op.drop_column("document", "secondary_only_sync_pending")

    op.drop_column("index_attempt", "is_synthetic_seed")

    # Dropping the table drops its indexes too.
    op.drop_table("port_attempt")
