"""add status to mcp server and make auth fields nullable

Revision ID: 6f835fa21628
Revises: 3c9a65f1207f
Create Date: 2025-11-21 13:18:19.466924

"""

from alembic import op
import sqlalchemy as sa
from onyx.db.enums import (
    MCPTransport,
    MCPAuthenticationType,
    MCPAuthenticationPerformer,
    MCPServerStatus,
)

# revision identifiers, used by Alembic.
revision = "6f835fa21628"
down_revision = "3c9a65f1207f"
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
