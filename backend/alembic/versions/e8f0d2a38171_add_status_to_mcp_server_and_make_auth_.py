"""add status to mcp server and make auth fields nullable

Revision ID: e8f0d2a38171
Revises: ed9e44312505
Create Date: 2025-11-28 11:15:37.667340

"""

from alembic import op
import sqlalchemy as sa
from onyx.db.enums import (  # type: ignore[import-untyped]
    MCPTransport,
    MCPAuthenticationType,
    MCPAuthenticationPerformer,
    MCPServerStatus,
)

# revision identifiers, used by Alembic.
revision = "e8f0d2a38171"
down_revision = "ed9e44312505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make auth fields nullable
    op.alter_column(
        "mcp_server",
        "transport",
        existing_type=sa.Enum(MCPTransport, name="mcp_transport", native_enum=False),
        nullable=True,
    )

    op.alter_column(
        "mcp_server",
        "auth_type",
        existing_type=sa.Enum(
            MCPAuthenticationType, name="mcp_authentication_type", native_enum=False
        ),
        nullable=True,
    )

    op.alter_column(
        "mcp_server",
        "auth_performer",
        existing_type=sa.Enum(
            MCPAuthenticationPerformer,
            name="mcp_authentication_performer",
            native_enum=False,
        ),
        nullable=True,
    )

    # Add status column with default
    op.add_column(
        "mcp_server",
        sa.Column(
            "status",
            sa.Enum(MCPServerStatus, name="mcp_server_status", native_enum=False),
            nullable=False,
            server_default="CREATED",
        ),
    )

    # For existing records, mark status as CONNECTED
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
        UPDATE mcp_server
        SET status = 'CONNECTED'
        WHERE status != 'CONNECTED'
        and admin_connection_config_id IS NOT NULL
        """
        )
    )


def downgrade() -> None:
    # Remove status column
    op.drop_column("mcp_server", "status")

    # Make auth fields non-nullable (set defaults first)
    op.execute(
        "UPDATE mcp_server SET transport = 'STREAMABLE_HTTP' WHERE transport IS NULL"
    )
    op.execute("UPDATE mcp_server SET auth_type = 'NONE' WHERE auth_type IS NULL")
    op.execute(
        "UPDATE mcp_server SET auth_performer = 'ADMIN' WHERE auth_performer IS NULL"
    )

    op.alter_column(
        "mcp_server",
        "transport",
        existing_type=sa.Enum(MCPTransport, name="mcp_transport", native_enum=False),
        nullable=False,
    )
    op.alter_column(
        "mcp_server",
        "auth_type",
        existing_type=sa.Enum(
            MCPAuthenticationType, name="mcp_authentication_type", native_enum=False
        ),
        nullable=False,
    )
    op.alter_column(
        "mcp_server",
        "auth_performer",
        existing_type=sa.Enum(
            MCPAuthenticationPerformer,
            name="mcp_authentication_performer",
            native_enum=False,
        ),
        nullable=False,
    )
