"""targeted reindex schema: targeted_reindex_job, targeted_reindex_job_target,
targeted_reindex_job_id on index_attempt

Revision ID: 31bd8c17325e
Revises: 14162713706c
Create Date: 2026-04-30 15:35:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "31bd8c17325e"
down_revision = "14162713706c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Lifecycle table.
    op.create_table(
        "targeted_reindex_job",
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
            sa.Enum(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "CANCELED",
                "FAILED",
                "COMPLETED_WITH_ERRORS",
                name="indexingstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
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
        "ix_targeted_reindex_job_requested_by_user_id",
        "targeted_reindex_job",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_targeted_reindex_job_requested_at",
        "targeted_reindex_job",
        ["requested_at"],
    )
    op.create_index(
        "ix_targeted_reindex_job_status",
        "targeted_reindex_job",
        ["status"],
    )

    # 2. Per-doc target rows.
    op.create_table(
        "targeted_reindex_job_target",
        sa.Column(
            "targeted_reindex_job_id",
            sa.Integer(),
            sa.ForeignKey("targeted_reindex_job.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "cc_pair_id",
            sa.Integer(),
            sa.ForeignKey("connector_credential_pair.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_error_id",
            sa.Integer(),
            sa.ForeignKey("index_attempt_errors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_targeted_reindex_job_target_source_error_id",
        "targeted_reindex_job_target",
        ["source_error_id"],
    )
    op.create_index(
        "ix_targeted_reindex_job_target_cc_pair_doc",
        "targeted_reindex_job_target",
        ["cc_pair_id", "document_id"],
    )

    # 3. FK on index_attempt linking synthetic targeted-reindex attempts
    #    back to their job. NULL on full-run attempts.
    op.add_column(
        "index_attempt",
        sa.Column(
            "targeted_reindex_job_id",
            sa.Integer(),
            sa.ForeignKey("targeted_reindex_job.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_index_attempt_targeted_reindex_job_id",
        "index_attempt",
        ["targeted_reindex_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_index_attempt_targeted_reindex_job_id",
        table_name="index_attempt",
    )
    op.drop_column("index_attempt", "targeted_reindex_job_id")

    op.drop_index(
        "ix_targeted_reindex_job_target_cc_pair_doc",
        table_name="targeted_reindex_job_target",
    )
    op.drop_index(
        "ix_targeted_reindex_job_target_source_error_id",
        table_name="targeted_reindex_job_target",
    )
    op.drop_table("targeted_reindex_job_target")

    op.drop_index("ix_targeted_reindex_job_status", table_name="targeted_reindex_job")
    op.drop_index(
        "ix_targeted_reindex_job_requested_at", table_name="targeted_reindex_job"
    )
    op.drop_index(
        "ix_targeted_reindex_job_requested_by_user_id",
        table_name="targeted_reindex_job",
    )
    op.drop_table("targeted_reindex_job")
