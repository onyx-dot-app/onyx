"""add inbound mcp oauth grants and tokens

Revision ID: 84c15650b1ad
Revises: b3e7c1d9a4f2
Create Date: 2026-10-05 09:44:00.334036

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from shared_configs.configs import MULTI_TENANT


# revision identifiers, used by Alembic.
revision = "84c15650b1ad"
down_revision = "b3e7c1d9a4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not MULTI_TENANT:
        op.create_table(
            "mcp_oauth_client",
            sa.Column("client_id", sa.String(64), primary_key=True),
            sa.Column("client_metadata", postgresql.JSONB(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "last_used_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            schema="public",
        )
        op.create_index(
            "ix_mcp_oauth_client_last_used_at",
            "mcp_oauth_client",
            ["last_used_at"],
            schema="public",
        )
    op.create_table(
        "mcp_oauth_grant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(2048), nullable=False),
        sa.Column("client_name", sa.String(256), nullable=False),
        sa.Column("resource", sa.String(2048), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mcp_oauth_grant_user_created", "mcp_oauth_grant", ["user_id", "created_at"]
    )
    op.create_index("ix_mcp_oauth_grant_expires_at", "mcp_oauth_grant", ["expires_at"])
    op.create_table(
        "mcp_oauth_token",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "grant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_oauth_grant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(7), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('access', 'refresh')", name="ck_mcp_oauth_token_kind"
        ),
    )
    op.create_index("ix_mcp_oauth_token_grant_id", "mcp_oauth_token", ["grant_id"])
    op.create_index("ix_mcp_oauth_token_expires_at", "mcp_oauth_token", ["expires_at"])


def downgrade() -> None:
    op.drop_table("mcp_oauth_token")
    op.drop_table("mcp_oauth_grant")
    if not MULTI_TENANT:
        op.drop_table("mcp_oauth_client", schema="public")
