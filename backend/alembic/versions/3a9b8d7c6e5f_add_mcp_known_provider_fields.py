"""add mcp known-provider oauth fields

Revision ID: 3a9b8d7c6e5f
Revises: 4d545225fd82
Create Date: 2026-05-31 13:40:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.db.enums import MCPOAuthProviderMode

# revision identifiers, used by Alembic.
revision = "3a9b8d7c6e5f"
down_revision = "4d545225fd82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server",
        sa.Column(
            "oauth_provider_mode",
            sa.Enum(
                MCPOAuthProviderMode,
                name="mcp_oauth_provider_mode",
                native_enum=False,
            ),
            nullable=False,
            server_default=MCPOAuthProviderMode.AUTO_DISCOVERY.value,
        ),
    )
    op.add_column(
        "mcp_server",
        sa.Column("oauth_authorization_endpoint", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_server",
        sa.Column("oauth_token_endpoint", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_server",
        sa.Column("oauth_scopes_override", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "mcp_server",
        sa.Column("oauth_additional_auth_params", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "oauth_additional_auth_params")
    op.drop_column("mcp_server", "oauth_scopes_override")
    op.drop_column("mcp_server", "oauth_token_endpoint")
    op.drop_column("mcp_server", "oauth_authorization_endpoint")
    op.drop_column("mcp_server", "oauth_provider_mode")
