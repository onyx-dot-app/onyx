"""Add avatar tables

Revision ID: a1b2c3d4e5f6
Revises: 87c52ec39f84
Create Date: 2025-01-15 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "87c52ec39f84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create avatar table
    op.create_table(
        "avatar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "default_query_mode",
            sa.String(),
            nullable=False,
            default="owned_documents",
        ),
        sa.Column("allow_accessible_mode", sa.Boolean(), nullable=False, default=True),
        sa.Column("auto_approve_rules", postgresql.JSONB(), nullable=True),
        sa.Column("show_query_in_request", sa.Boolean(), nullable=False, default=True),
        sa.Column("max_requests_per_day", sa.Integer(), nullable=True, default=100),
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
    )

    # Create avatar_permission_request table
    op.create_table(
        "avatar_permission_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "avatar_id",
            sa.Integer(),
            sa.ForeignKey("avatar.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cached_answer", sa.Text(), nullable=True),
        sa.Column("cached_search_doc_ids", postgresql.JSONB(), nullable=True),
        sa.Column("answer_quality_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, default="pending"),
        sa.Column("denial_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create indexes for avatar_permission_request
    op.create_index(
        "ix_avatar_permission_request_avatar_id",
        "avatar_permission_request",
        ["avatar_id"],
    )
    op.create_index(
        "ix_avatar_permission_request_requester_id",
        "avatar_permission_request",
        ["requester_id"],
    )
    op.create_index(
        "ix_avatar_permission_request_status",
        "avatar_permission_request",
        ["status"],
    )
    op.create_index(
        "ix_avatar_permission_request_avatar_status",
        "avatar_permission_request",
        ["avatar_id", "status"],
    )
    op.create_index(
        "ix_avatar_permission_request_requester_created",
        "avatar_permission_request",
        ["requester_id", "created_at"],
    )

    # Create avatar_query table
    op.create_table(
        "avatar_query",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "avatar_id",
            sa.Integer(),
            sa.ForeignKey("avatar.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_mode", sa.String(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Create indexes for avatar_query
    op.create_index(
        "ix_avatar_query_avatar_id",
        "avatar_query",
        ["avatar_id"],
    )
    op.create_index(
        "ix_avatar_query_requester_id",
        "avatar_query",
        ["requester_id"],
    )
    op.create_index(
        "ix_avatar_query_rate_limit",
        "avatar_query",
        ["avatar_id", "requester_id", "created_at"],
    )


def downgrade() -> None:
    # Drop avatar_query table and indexes
    op.drop_index("ix_avatar_query_rate_limit", table_name="avatar_query")
    op.drop_index("ix_avatar_query_requester_id", table_name="avatar_query")
    op.drop_index("ix_avatar_query_avatar_id", table_name="avatar_query")
    op.drop_table("avatar_query")

    # Drop avatar_permission_request table and indexes
    op.drop_index(
        "ix_avatar_permission_request_requester_created",
        table_name="avatar_permission_request",
    )
    op.drop_index(
        "ix_avatar_permission_request_avatar_status",
        table_name="avatar_permission_request",
    )
    op.drop_index(
        "ix_avatar_permission_request_status",
        table_name="avatar_permission_request",
    )
    op.drop_index(
        "ix_avatar_permission_request_requester_id",
        table_name="avatar_permission_request",
    )
    op.drop_index(
        "ix_avatar_permission_request_avatar_id",
        table_name="avatar_permission_request",
    )
    op.drop_table("avatar_permission_request")

    # Drop avatar table
    op.drop_table("avatar")
