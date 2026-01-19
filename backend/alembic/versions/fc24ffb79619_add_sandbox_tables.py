"""Add sandbox tables (cc4a)

Revision ID: fc24ffb79619
Revises: d1b637d7050a
Create Date: 2026-01-19 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "fc24ffb79619"
down_revision = "d1b637d7050a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create sandbox table
    op.create_table(
        "sandbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("directory_path", sa.String(), nullable=False),
        sa.Column("agent_pid", sa.Integer(), nullable=True),
        sa.Column("nextjs_pid", sa.Integer(), nullable=True),
        sa.Column("nextjs_port", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("ix_sandbox_tenant_id", "sandbox", ["tenant_id"], unique=False)
    op.create_index(
        "ix_sandbox_tenant_status", "sandbox", ["tenant_id", "status"], unique=False
    )

    # Create sandbox_snapshot table
    op.create_table(
        "sandbox_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sandbox_snapshot_session_id",
        "sandbox_snapshot",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_sandbox_snapshot_tenant_id", "sandbox_snapshot", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_sandbox_snapshot_tenant_id", table_name="sandbox_snapshot")
    op.drop_index("ix_sandbox_snapshot_session_id", table_name="sandbox_snapshot")
    op.drop_table("sandbox_snapshot")
    op.drop_index("ix_sandbox_tenant_status", table_name="sandbox")
    op.drop_index("ix_sandbox_tenant_id", table_name="sandbox")
    op.drop_table("sandbox")
