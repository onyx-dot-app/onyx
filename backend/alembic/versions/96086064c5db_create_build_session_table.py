"""create_build_session_table

Revision ID: 96086064c5db
Revises: 8b5ce697290e
Create Date: 2026-01-19 14:47:38.156803

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "96086064c5db"
down_revision = "8b5ce697290e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create build_session status enum
    build_session_status_enum = sa.Enum(
        "active",
        "idle",
        name="buildsessionstatus",
        native_enum=False,
    )

    # Create build_session table
    op.create_table(
        "build_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "status",
            build_session_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for build_session
    op.create_index(
        "ix_build_session_user_created",
        "build_session",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_build_session_status",
        "build_session",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_build_session_status", table_name="build_session")
    op.drop_index("ix_build_session_user_created", table_name="build_session")

    # Drop table
    op.drop_table("build_session")

    # Drop enum
    sa.Enum(name="buildsessionstatus").drop(op.get_bind(), checkfirst=True)
