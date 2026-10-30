"""add connector_event_inbox

One pending document change pushed to Onyx by an event-based connector. The
webhook server writes a row per event; a later drain claims rows inside an
ordinary docfetching run.

Revision ID: d451809a0c3e
Revises: 3e30a81ec3bd
Create Date: 2026-10-30 11:06:33.039774

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "d451809a0c3e"
down_revision = "3e30a81ec3bd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_event_inbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_key", sa.String(), nullable=False),
        sa.Column("file_id", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("index_attempt_id", sa.Integer(), nullable=True),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
            ondelete="CASCADE",
        ),
        # RESTRICT so file store cleanup cannot strand a pending row.
        sa.ForeignKeyConstraint(
            ["file_id"], ["file_record.file_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["index_attempt_id"], ["index_attempt.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        # Idempotent receipt: the writer inserts ON CONFLICT DO NOTHING.
        sa.UniqueConstraint(
            "connector_credential_pair_id",
            "event_key",
            name="uq_connector_event_inbox_pair_event_key",
        ),
    )
    op.create_index(
        "ix_connector_event_inbox_claim",
        "connector_event_inbox",
        ["available_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        op.f("ix_connector_event_inbox_index_attempt_id"),
        "connector_event_inbox",
        ["index_attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_event_inbox_pair_document",
        "connector_event_inbox",
        ["connector_credential_pair_id", "document_id"],
        unique=False,
    )
    op.create_index(
        "ix_connector_event_inbox_pair_status",
        "connector_event_inbox",
        ["connector_credential_pair_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_connector_event_inbox_pair_status", table_name="connector_event_inbox"
    )
    op.drop_index(
        "ix_connector_event_inbox_pair_document", table_name="connector_event_inbox"
    )
    op.drop_index(
        op.f("ix_connector_event_inbox_index_attempt_id"),
        table_name="connector_event_inbox",
    )
    op.drop_index(
        "ix_connector_event_inbox_claim",
        table_name="connector_event_inbox",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("connector_event_inbox")
