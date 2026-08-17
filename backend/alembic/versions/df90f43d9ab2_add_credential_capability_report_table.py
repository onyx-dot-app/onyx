"""add credential capability report table

Latest-only capability-check reports, one row per (credential, connector-scope):
``connector_id`` NULL is the config-less credential-time report, non-NULL is one
per attached connector. The two partial unique indexes enforce the upsert
semantics.

Revision ID: df90f43d9ab2
Revises: c5d9662b3c50
Create Date: 2026-08-13 10:57:12.982708

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus

# revision identifiers, used by Alembic.
revision = "df90f43d9ab2"
down_revision = "c5d9662b3c50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_capability_report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Enum(DocumentSource, native_enum=False), nullable=False),
        sa.Column("connector_config_hash", sa.String(), nullable=True),
        sa.Column(
            "trigger",
            sa.Enum(CapabilityCheckTrigger, native_enum=False),
            nullable=False,
        ),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column(
            "run_status",
            sa.Enum(CapabilityReportRunStatus, native_enum=False),
            nullable=False,
        ),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["connector.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_credential_capability_report_credential_id",
        "credential_capability_report",
        ["credential_id"],
    )
    op.create_index(
        "uq_capability_report_connector_scope",
        "credential_capability_report",
        ["credential_id", "connector_id"],
        unique=True,
        postgresql_where=sa.text("connector_id IS NOT NULL"),
    )
    op.create_index(
        "uq_capability_report_credential_scope",
        "credential_capability_report",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("connector_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("credential_capability_report")
