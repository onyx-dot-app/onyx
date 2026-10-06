"""add capability check run table

Append-only capability-check run history: one row per run attempt, holding the
run's inputs (config snapshot and subset, never credential material), results,
and lifecycle. Ships dark; the latest-only ``credential_capability_report``
table remains the compatibility pointer for existing consumers.

Revision ID: 6776fa94b6f6
Revises: 84c15650b1ad
Create Date: 2026-10-05 15:02:11.802129

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus

# revision identifiers, used by Alembic.
revision = "6776fa94b6f6"
down_revision = "84c15650b1ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_check_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Enum(DocumentSource, native_enum=False), nullable=False),
        sa.Column("creation_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "trigger",
            sa.Enum(CapabilityCheckTrigger, native_enum=False),
            nullable=False,
        ),
        sa.Column("check_ids_requested", postgresql.JSONB(), nullable=True),
        sa.Column("connector_config", postgresql.JSONB(), nullable=True),
        sa.Column("connector_config_hash", sa.String(), nullable=True),
        sa.Column(
            "run_status",
            sa.Enum(CapabilityReportRunStatus, native_enum=False),
            nullable=False,
        ),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["connector.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    # Serves the input-hash dedup lookup and, by prefix, every per-credential
    # query (scoped listings, latest-by-scope).
    op.create_index(
        "ix_capability_check_run_dedup",
        "capability_check_run",
        ["credential_id", "connector_config_hash", "run_started_at"],
    )
    op.create_index(
        "ix_capability_check_run_creation_session_id",
        "capability_check_run",
        ["creation_session_id"],
    )
    # Serves the retention sweep's delete-by-age.
    op.create_index(
        "ix_capability_check_run_run_started_at",
        "capability_check_run",
        ["run_started_at"],
    )


def downgrade() -> None:
    op.drop_table("capability_check_run")
