"""scheduled tasks

Adds the Scheduled Tasks feature surface for Craft:
- New tables: scheduled_task, scheduled_task_run.
- New BuildSession.origin column (so scheduled-run sessions can be filtered
  out of the Craft sidebar).
- Replacement composite index on build_session (user_id, origin, created_at).
- Two new NotificationType values (the column is a non-native enum / varchar,
  so no DDL is required; this migration is the marker for the addition).

Revision ID: 28429dd43807
Revises: 0df3c40e902a
Create Date: 2026-05-12 11:36:44.389608

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "28429dd43807"
down_revision = "0df3c40e902a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Reusable non-native enum types. native_enum=False mirrors the rest of
    # the Craft tables (the actual storage is a varchar with a CHECK
    # constraint).
    # ------------------------------------------------------------------
    session_origin_enum = sa.Enum(
        "INTERACTIVE",
        "SCHEDULED",
        name="sessionorigin",
        native_enum=False,
    )
    scheduled_task_status_enum = sa.Enum(
        "ACTIVE",
        "PAUSED",
        name="scheduledtaskstatus",
        native_enum=False,
    )
    scheduled_task_run_status_enum = sa.Enum(
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
        "AWAITING_APPROVAL",
        name="scheduledtaskrunstatus",
        native_enum=False,
    )
    scheduled_task_trigger_source_enum = sa.Enum(
        "SCHEDULED",
        "MANUAL_RUN_NOW",
        name="scheduledtasktriggersource",
        native_enum=False,
    )

    # ------------------------------------------------------------------
    # BuildSession: add `origin` column + swap the user-listing index for
    # one that covers (user_id, origin, created_at DESC).
    # ------------------------------------------------------------------
    op.add_column(
        "build_session",
        sa.Column(
            "origin",
            session_origin_enum,
            nullable=False,
            server_default="INTERACTIVE",
        ),
    )

    # The old index supported (user_id, created_at DESC). The new sidebar
    # query also filters on origin, so we replace with a composite covering
    # index. drop_index is conditional in case earlier deployments removed
    # it manually; the create is unconditional.
    op.execute("DROP INDEX IF EXISTS ix_build_session_user_created")
    op.create_index(
        "ix_build_session_user_origin_created",
        "build_session",
        ["user_id", "origin", sa.text("created_at DESC")],
        unique=False,
    )

    # ------------------------------------------------------------------
    # scheduled_task
    # ------------------------------------------------------------------
    op.create_table(
        "scheduled_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cron_expression", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("editor_mode", sa.String(), nullable=False),
        sa.Column(
            "status",
            scheduled_task_status_enum,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_task_dispatch",
        "scheduled_task",
        ["status", "deleted", "next_run_at"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_task_user_created",
        "scheduled_task",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )

    # ------------------------------------------------------------------
    # scheduled_task_run
    # ------------------------------------------------------------------
    op.create_table(
        "scheduled_task_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            scheduled_task_run_status_enum,
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column(
            "trigger_source",
            scheduled_task_trigger_source_enum,
            nullable=False,
        ),
        sa.Column("skip_reason", sa.String(), nullable=True),
        sa.Column("error_class", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_task_run_task_started",
        "scheduled_task_run",
        ["task_id", sa.text("started_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_task_run_status",
        "scheduled_task_run",
        ["status"],
        unique=False,
    )
    # Session-view banner lookup: get_scheduled_run_context filters by
    # session_id on every session open.
    op.create_index(
        "ix_scheduled_task_run_session",
        "scheduled_task_run",
        ["session_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # NotificationType:
    #   The `notification.notif_type` column is declared with
    #   `native_enum=False` (see backend/onyx/db/models.py), i.e. stored as
    #   a varchar with no native PG enum type. Adding new enum values is
    #   therefore a pure Python-side change — no DDL needed.
    #
    #   New values added (in onyx/configs/constants.py):
    #     - "scheduled_task_failed"
    #     - "scheduled_task_awaiting_approval"
    # ------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index("ix_scheduled_task_run_session", table_name="scheduled_task_run")
    op.drop_index("ix_scheduled_task_run_status", table_name="scheduled_task_run")
    op.drop_index("ix_scheduled_task_run_task_started", table_name="scheduled_task_run")
    op.drop_table("scheduled_task_run")

    op.drop_index("ix_scheduled_task_user_created", table_name="scheduled_task")
    op.drop_index("ix_scheduled_task_dispatch", table_name="scheduled_task")
    op.drop_table("scheduled_task")

    op.drop_index("ix_build_session_user_origin_created", table_name="build_session")
    # Restore the previous (user_id, created_at DESC) index.
    op.create_index(
        "ix_build_session_user_created",
        "build_session",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.drop_column("build_session", "origin")
