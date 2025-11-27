"""add status to mcp server and make auth fields nullable

Revision ID: fbf09ef1abfe
Revises: c7e9f4a3b2d1
Create Date: 2025-11-27 16:45:09.775152

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
revision = "fbf09ef1abfe"
down_revision = "c7e9f4a3b2d1"
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
