"""Add flow automation tables

Revision ID: b7f2c4a19d33
Revises: ad99acb9be41
Create Date: 2026-06-03 10:14:52.118374

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b7f2c4a19d33"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "PAUSED", name="flowstatus", native_enum=False),
            nullable=False,
            server_default="PAUSED",
        ),
        sa.Column("draft_spec", postgresql.JSONB(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column(
            "deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_flow_user_created",
        "flow",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "flow_version",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["flow_id"], ["flow.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("flow_id", "version", name="uq_flow_version_flow_version"),
    )

    op.create_table(
        "flow_trigger",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "SCHEDULE",
                "WEBHOOK",
                "MANUAL",
                name="flowtriggerkind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_secret", sa.LargeBinary(), nullable=True),  # EncryptedString
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["flow_id"], ["flow.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_flow_trigger_dispatch", "flow_trigger", ["enabled", "next_run_at"]
    )
    op.create_index("ix_flow_trigger_flow", "flow_trigger", ["flow_id"])

    op.create_table(
        "flow_run",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "trigger_source",
            sa.Enum(
                "SCHEDULE",
                "WEBHOOK",
                "MANUAL",
                "TEST",
                name="flowtriggersource",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "SKIPPED",
                name="flowrunstatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column("trigger_payload", postgresql.JSONB(), nullable=True),
        sa.Column("skip_reason", sa.String(), nullable=True),
        sa.Column("error_class", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flow.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flow_version_id"], ["flow_version.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"], ["flow_trigger.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_flow_run_flow_started",
        "flow_run",
        ["flow_id", sa.text("started_at DESC")],
    )
    op.create_index("ix_flow_run_status", "flow_run", ["status"])

    op.create_table(
        "flow_node_run",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "HTTP",
                "TRANSFORM",
                "CONDITION",
                "AI",
                name="flownodekind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "SKIPPED",
                name="flownoderunstatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column(
            "item_index", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("error_class", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["flow_run.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "run_id", "node_id", "item_index", name="uq_flow_node_run_identity"
        ),
    )
    op.create_index("ix_flow_node_run_run", "flow_node_run", ["run_id"])


def downgrade() -> None:
    op.drop_table("flow_node_run")
    op.drop_table("flow_run")
    op.drop_table("flow_trigger")
    op.drop_table("flow_version")
    op.drop_table("flow")
