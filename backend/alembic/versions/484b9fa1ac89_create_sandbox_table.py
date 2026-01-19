"""create_sandbox_table

Revision ID: 484b9fa1ac89
Revises: 96086064c5db
Create Date: 2026-01-19 14:47:52.829749

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "484b9fa1ac89"
down_revision = "96086064c5db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create sandbox status enum
    sandbox_status_enum = sa.Enum(
        "provisioning",
        "running",
        "idle",
        "terminated",
        name="sandboxstatus",
        native_enum=False,
    )

    # Create sandbox table
    op.create_table(
        "sandbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("container_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sandbox_status_enum,
            nullable=False,
            server_default="provisioning",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for sandbox
    op.create_index(
        "ix_sandbox_status",
        "sandbox",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_sandbox_container_id",
        "sandbox",
        ["container_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_sandbox_container_id", table_name="sandbox")
    op.drop_index("ix_sandbox_status", table_name="sandbox")

    # Drop table
    op.drop_table("sandbox")

    # Drop enum
    sa.Enum(name="sandboxstatus").drop(op.get_bind(), checkfirst=True)
