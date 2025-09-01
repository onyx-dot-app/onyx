"""add_mcp_server_and_connection_config_models

Revision ID: 7ed603b64d5a
Revises: b329d00a9ea6
Create Date: 2025-07-28 17:35:59.900680

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from onyx.db.enums import MCPAuthenticationType

# revision identifiers, used by Alembic.
revision = "7ed603b64d5a"
down_revision = "b329d00a9ea6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tables and columns for MCP Server support"""

    # 1. MCP Server main table (no FK constraints yet to avoid circular refs)
    op.create_table(
        "mcp_server",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("server_url", sa.String(), nullable=False),
        sa.Column(
            "auth_type",
            sa.Enum(
                MCPAuthenticationType,
                name="mcp_authentication_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("admin_connection_config_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),  # type: ignore
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),  # type: ignore
            nullable=False,
        ),
    )

    # 2. MCP Connection Config table (can reference mcp_server now that it exists)
    op.create_table(
        "mcp_connection_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mcp_server_id", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(), nullable=False, default=""),
        sa.Column("config", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),  # type: ignore
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),  # type: ignore
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], ondelete="CASCADE"
        ),
    )

    # Helpful indexes
    op.create_index(
        "ix_mcp_connection_config_server_user",
        "mcp_connection_config",
        ["mcp_server_id", "user_email"],
    )
    op.create_index(
        "ix_mcp_connection_config_user_email",
        "mcp_connection_config",
        ["user_email"],
    )

    # 3. Add the back-references from mcp_server to connection configs
    op.create_foreign_key(
        "mcp_server_admin_config_fk",
        "mcp_server",
        "mcp_connection_config",
        ["admin_connection_config_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. Association / access-control tables
    op.create_table(
        "mcp_server__user",
        sa.Column("mcp_server_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.UUID(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "mcp_server__user_group",
        sa.Column("mcp_server_id", sa.Integer(), primary_key=True),
        sa.Column("user_group_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_group_id"], ["user_group.id"]),
    )

    # 5. Update existing `tool` table – allow tools to belong to an MCP server
    op.add_column(
        "tool",
        sa.Column("mcp_server_id", sa.Integer(), nullable=True),
    )
    # Add column for MCP tool input schema
    op.add_column(
        "tool",
        sa.Column("mcp_input_schema", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "tool_mcp_server_fk",
        "tool",
        "mcp_server",
        ["mcp_server_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 6. Update persona__tool foreign keys to cascade delete
    # This ensures that when a tool is deleted (including via MCP server deletion),
    # the corresponding persona__tool rows are also deleted
    op.drop_constraint(
        "persona__tool_tool_id_fkey", "persona__tool", type_="foreignkey"
    )
    op.drop_constraint(
        "persona__tool_persona_id_fkey", "persona__tool", type_="foreignkey"
    )

    op.create_foreign_key(
        "persona__tool_persona_id_fkey",
        "persona__tool",
        "persona",
        ["persona_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "persona__tool_tool_id_fkey",
        "persona__tool",
        "tool",
        ["tool_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 7. Update research_agent_iteration_sub_step foreign key to SET NULL on delete
    # This ensures that when a tool is deleted, the sub_step_tool_id is set to NULL
    # instead of causing a foreign key constraint violation
    op.drop_constraint(
        "research_agent_iteration_sub_step_sub_step_tool_id_fkey",
        "research_agent_iteration_sub_step",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "research_agent_iteration_sub_step_sub_step_tool_id_fkey",
        "research_agent_iteration_sub_step",
        "tool",
        ["sub_step_tool_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Drop all MCP-related tables / columns"""

    # # # 1. Drop FK & columns from tool
    # op.drop_constraint("tool_mcp_server_fk", "tool", type_="foreignkey")
    op.execute("DELETE FROM tool WHERE mcp_server_id IS NOT NULL")

    op.drop_constraint(
        "research_agent_iteration_sub_step_sub_step_tool_id_fkey",
        "research_agent_iteration_sub_step",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "research_agent_iteration_sub_step_sub_step_tool_id_fkey",
        "research_agent_iteration_sub_step",
        "tool",
        ["sub_step_tool_id"],
        ["id"],
    )

    # Restore original persona__tool foreign keys (without CASCADE)
    op.drop_constraint(
        "persona__tool_persona_id_fkey", "persona__tool", type_="foreignkey"
    )
    op.drop_constraint(
        "persona__tool_tool_id_fkey", "persona__tool", type_="foreignkey"
    )

    op.create_foreign_key(
        "persona__tool_persona_id_fkey",
        "persona__tool",
        "persona",
        ["persona_id"],
        ["id"],
    )
    op.create_foreign_key(
        "persona__tool_tool_id_fkey",
        "persona__tool",
        "tool",
        ["tool_id"],
        ["id"],
    )
    op.drop_column("tool", "mcp_input_schema")
    op.drop_column("tool", "mcp_server_id")

    # 2. Drop association tables
    op.drop_table("mcp_server__user_group")
    op.drop_table("mcp_server__user")

    # 3. Drop FK from mcp_server to connection configs
    op.drop_constraint("mcp_server_admin_config_fk", "mcp_server", type_="foreignkey")

    # 4. Drop connection config indexes & table
    op.drop_index(
        "ix_mcp_connection_config_user_email", table_name="mcp_connection_config"
    )
    op.drop_index(
        "ix_mcp_connection_config_server_user", table_name="mcp_connection_config"
    )
    op.drop_table("mcp_connection_config")

    # 5. Finally drop mcp_server table
    op.drop_table("mcp_server")
