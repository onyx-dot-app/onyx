"""retry_job table + index_attempt.attempt_type discriminator + index_attempt_errors retry audit columns

Revision ID: eeda3dae20c0
Revises: 14162713706c
Create Date: 2026-04-29 15:35:23.923345

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.db.enums import IndexAttemptType
from onyx.db.enums import IndexingStatus


# revision identifiers, used by Alembic.
revision = "eeda3dae20c0"
down_revision = "14162713706c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create retry_job table.
    op.create_table(
        "retry_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(IndexingStatus, native_enum=False),
            server_default="NOT_STARTED",
            nullable=False,
        ),
        sa.Column(
            "error_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("resolved_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "still_failing_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "resolved_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_retry_job_status",
        "retry_job",
        ["status"],
    )
    op.create_index(
        "ix_retry_job_requested_by_user_id",
        "retry_job",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_retry_job_requested_at",
        "retry_job",
        ["requested_at"],
    )

    # 2. Add attempt_type discriminator + retry_job_id FK on index_attempt.
    #    `attempt_type` defaults to FULL_RUN so existing rows backfill safely.
    op.add_column(
        "index_attempt",
        sa.Column(
            "attempt_type",
            sa.Enum(IndexAttemptType, native_enum=False),
            server_default="FULL_RUN",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_index_attempt_attempt_type",
        "index_attempt",
        ["attempt_type"],
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "retry_job_id",
            sa.Integer(),
            sa.ForeignKey("retry_job.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_index_attempt_retry_job_id",
        "index_attempt",
        ["retry_job_id"],
    )

    # 3. Additive retry-audit columns on index_attempt_errors. All nullable
    #    or default-backed; existing rows stay untouched.
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "last_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "last_retry_job_id",
            sa.Integer(),
            sa.ForeignKey("retry_job.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_index_attempt_errors_last_retry_job_id",
        "index_attempt_errors",
        ["last_retry_job_id"],
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_index_attempt_errors_resolved_by_user_id",
        "index_attempt_errors",
        ["resolved_by_user_id"],
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "retry_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "index_attempt_errors",
        sa.Column(
            "connector_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Reverse order of upgrade: drop columns from index_attempt_errors,
    # then index_attempt, then drop retry_job.
    op.drop_column("index_attempt_errors", "connector_metadata")
    op.drop_column("index_attempt_errors", "retry_history")
    op.drop_index(
        "ix_index_attempt_errors_resolved_by_user_id",
        table_name="index_attempt_errors",
    )
    op.drop_column("index_attempt_errors", "resolved_by_user_id")
    op.drop_column("index_attempt_errors", "resolved_at")
    op.drop_index(
        "ix_index_attempt_errors_last_retry_job_id",
        table_name="index_attempt_errors",
    )
    op.drop_column("index_attempt_errors", "last_retry_job_id")
    op.drop_column("index_attempt_errors", "last_retry_at")
    op.drop_column("index_attempt_errors", "retry_count")

    op.drop_index("ix_index_attempt_retry_job_id", table_name="index_attempt")
    op.drop_column("index_attempt", "retry_job_id")
    op.drop_index("ix_index_attempt_attempt_type", table_name="index_attempt")
    op.drop_column("index_attempt", "attempt_type")

    op.drop_index("ix_retry_job_requested_at", table_name="retry_job")
    op.drop_index("ix_retry_job_requested_by_user_id", table_name="retry_job")
    op.drop_index("ix_retry_job_status", table_name="retry_job")
    op.drop_table("retry_job")
