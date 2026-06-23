"""add glomi_forge tables

Revision ID: 487a16fc2925
Revises: 2aedcb0ff5fd
Create Date: 2026-06-23 22:34:58.000438

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "487a16fc2925"
down_revision = "2aedcb0ff5fd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "glomi_forge_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "parent_chat_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column(
            "template_version",
            sa.String(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column(
            "sandbox_provider",
            sa.String(),
            nullable=False,
            server_default="daytona",
        ),
        sa.Column("sandbox_id", sa.String(), nullable=True),
        sa.Column("builder_session_id", sa.String(), nullable=True),
        sa.Column("preview_url", sa.String(), nullable=True),
        sa.Column("latest_output", postgresql.JSONB(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", postgresql.JSONB(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_glomi_forge_session_user",
        "glomi_forge_session",
        ["user_id"],
    )
    op.create_index(
        "ix_glomi_forge_session_status",
        "glomi_forge_session",
        ["status"],
    )

    op.create_table(
        "glomi_forge_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("glomi_forge_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("packet_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "session_id", "seq", name="uq_glomi_forge_event_session_seq"
        ),
    )
    op.create_index(
        "ix_glomi_forge_event_session_seq",
        "glomi_forge_event",
        ["session_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_glomi_forge_event_session_seq", table_name="glomi_forge_event")
    op.drop_table("glomi_forge_event")
    op.drop_index(
        "ix_glomi_forge_session_status", table_name="glomi_forge_session"
    )
    op.drop_index("ix_glomi_forge_session_user", table_name="glomi_forge_session")
    op.drop_table("glomi_forge_session")
