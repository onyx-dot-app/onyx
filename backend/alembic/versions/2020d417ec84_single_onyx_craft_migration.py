"""single onyx craft migration

Consolidates all buildmode/onyx craft tables into a single migration.

Tables created:
- build_session: User build sessions with status tracking
- sandbox: User-owned containerized environments (one per user)
- artifact: Build output files (web apps, documents, images)
- snapshot: Sandbox filesystem snapshots
- build_message: Conversation messages for build sessions

Existing table modified:
- connector_credential_pair: Added processing_mode column

Revision ID: 2020d417ec84
Revises: 41fa44bef321
Create Date: 2026-01-26 14:43:54.641405

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2020d417ec84"
down_revision = "41fa44bef321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # ENUMS
    # ==========================================================================

    # Build session status enum
    build_session_status_enum = sa.Enum(
        "active",
        "idle",
        name="buildsessionstatus",
        native_enum=False,
    )

    # Sandbox status enum
    sandbox_status_enum = sa.Enum(
        "provisioning",
        "running",
        "idle",
        "sleeping",
        "terminated",
        "failed",
        name="sandboxstatus",
        native_enum=False,
    )

    # Artifact type enum
    artifact_type_enum = sa.Enum(
        "web_app",
        "pptx",
        "docx",
        "markdown",
        "excel",
        "image",
        name="artifacttype",
        native_enum=False,
    )

    # ==========================================================================
    # BUILD_SESSION TABLE
    # ==========================================================================

    op.create_table(
        "build_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=True),
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
        sa.Column("nextjs_port", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

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

    # ==========================================================================
    # SANDBOX TABLE (user-owned, one per user)
    # ==========================================================================

    op.create_table(
        "sandbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
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
        sa.UniqueConstraint("user_id", name="sandbox_user_id_key"),
    )

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

    # ==========================================================================
    # ARTIFACT TABLE
    # ==========================================================================

    op.create_table(
        "artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", artifact_type_enum, nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
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
        "ix_artifact_session_created",
        "artifact",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_artifact_type",
        "artifact",
        ["type"],
        unique=False,
    )

    # ==========================================================================
    # SNAPSHOT TABLE
    # ==========================================================================

    op.create_table(
        "snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_snapshot_session_created",
        "snapshot",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )

    # ==========================================================================
    # BUILD_MESSAGE TABLE
    # ==========================================================================

    op.create_table(
        "build_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "turn_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum(
                "SYSTEM",
                "USER",
                "ASSISTANT",
                "DANSWER",
                name="messagetype",
                create_type=False,
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "message_metadata",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_build_message_session_turn",
        "build_message",
        ["session_id", "turn_index", sa.text("created_at ASC")],
        unique=False,
    )

    # ==========================================================================
    # CONNECTOR_CREDENTIAL_PAIR MODIFICATION
    # ==========================================================================

    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "processing_mode",
            sa.String(),
            nullable=False,
            server_default="regular",
        ),
    )


def downgrade() -> None:
    # ==========================================================================
    # CONNECTOR_CREDENTIAL_PAIR MODIFICATION
    # ==========================================================================

    op.drop_column("connector_credential_pair", "processing_mode")

    # ==========================================================================
    # BUILD_MESSAGE TABLE
    # ==========================================================================

    op.drop_index("ix_build_message_session_turn", table_name="build_message")
    op.drop_table("build_message")

    # ==========================================================================
    # SNAPSHOT TABLE
    # ==========================================================================

    op.drop_index("ix_snapshot_session_created", table_name="snapshot")
    op.drop_table("snapshot")

    # ==========================================================================
    # ARTIFACT TABLE
    # ==========================================================================

    op.drop_index("ix_artifact_type", table_name="artifact")
    op.drop_index("ix_artifact_session_created", table_name="artifact")
    op.drop_table("artifact")
    sa.Enum(name="artifacttype").drop(op.get_bind(), checkfirst=True)

    # ==========================================================================
    # SANDBOX TABLE
    # ==========================================================================

    op.drop_index("ix_sandbox_container_id", table_name="sandbox")
    op.drop_index("ix_sandbox_status", table_name="sandbox")
    op.drop_table("sandbox")
    sa.Enum(name="sandboxstatus").drop(op.get_bind(), checkfirst=True)

    # ==========================================================================
    # BUILD_SESSION TABLE
    # ==========================================================================

    op.drop_index("ix_build_session_status", table_name="build_session")
    op.drop_index("ix_build_session_user_created", table_name="build_session")
    op.drop_table("build_session")
    sa.Enum(name="buildsessionstatus").drop(op.get_bind(), checkfirst=True)
