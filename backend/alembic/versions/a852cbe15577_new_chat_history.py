"""New Chat History

Revision ID: a852cbe15577
Revises: 3c9a65f1207f
Create Date: 2025-11-08 15:16:37.781308

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a852cbe15577"
down_revision = "3c9a65f1207f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop research agent tables (if they exist)
    op.execute("DROP TABLE IF EXISTS research_agent_iteration_sub_step CASCADE")
    op.execute("DROP TABLE IF EXISTS research_agent_iteration CASCADE")

    # Drop agent sub query and sub question tables (if they exist)
    op.execute("DROP TABLE IF EXISTS agent__sub_query__search_doc CASCADE")
    op.execute("DROP TABLE IF EXISTS agent__sub_query CASCADE")
    op.execute("DROP TABLE IF EXISTS agent__sub_question CASCADE")

    # Update ChatMessage table
    # Rename parent_message to parent_message_id and make it a foreign key (if not already done)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'chat_message' AND column_name = 'parent_message'
    """
        )
    )
    if result.fetchone():
        op.alter_column(
            "chat_message", "parent_message", new_column_name="parent_message_id"
        )
        op.create_foreign_key(
            "fk_chat_message_parent_message_id",
            "chat_message",
            "chat_message",
            ["parent_message_id"],
            ["id"],
        )

    # Rename latest_child_message to latest_child_message_id and make it a foreign key (if not already done)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'chat_message' AND column_name = 'latest_child_message'
    """
        )
    )
    if result.fetchone():
        op.alter_column(
            "chat_message",
            "latest_child_message",
            new_column_name="latest_child_message_id",
        )
        op.create_foreign_key(
            "fk_chat_message_latest_child_message_id",
            "chat_message",
            "chat_message",
            ["latest_child_message_id"],
            ["id"],
        )

    # Add reasoning_tokens column (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'chat_message' AND column_name = 'reasoning_tokens'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "chat_message", sa.Column("reasoning_tokens", sa.Text(), nullable=True)
        )

    # Drop columns no longer needed (if they exist)
    for col in [
        "rephrased_query",
        "alternate_assistant_id",
        "overridden_model",
        "is_agentic",
        "refined_answer_improvement",
        "research_type",
        "research_plan",
        "research_answer_purpose",
    ]:
        result = conn.execute(
            sa.text(
                f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'chat_message' AND column_name = '{col}'
        """
            )
        )
        if result.fetchone():
            op.drop_column("chat_message", col)

    # Update ToolCall table
    # Add chat_session_id column (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'chat_session_id'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call",
            sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        )
        op.create_foreign_key(
            "fk_tool_call_chat_session_id",
            "tool_call",
            "chat_session",
            ["chat_session_id"],
            ["id"],
        )

    # Rename message_id to parent_chat_message_id and make nullable (if not already done)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'message_id'
    """
        )
    )
    if result.fetchone():
        op.alter_column(
            "tool_call",
            "message_id",
            new_column_name="parent_chat_message_id",
            nullable=True,
        )

    # Add parent_tool_call_id (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'parent_tool_call_id'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call", sa.Column("parent_tool_call_id", sa.Integer(), nullable=True)
        )
        op.create_foreign_key(
            "fk_tool_call_parent_tool_call_id",
            "tool_call",
            "tool_call",
            ["parent_tool_call_id"],
            ["id"],
        )

    # Add turn_number, tool_id (if not exists)
    for col_name in ["turn_number", "tool_id"]:
        result = conn.execute(
            sa.text(
                f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'tool_call' AND column_name = '{col_name}'
        """
            )
        )
        if not result.fetchone():
            op.add_column(
                "tool_call",
                sa.Column(col_name, sa.Integer(), nullable=False, server_default="0"),
            )

    # Add tab_number (nullable, no default for existing rows)
    result = conn.execute(
        sa.text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'tool_call' AND column_name = 'tab_number'
        """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call",
            sa.Column("tab_number", sa.Integer(), nullable=True),
        )

    # Add tool_call_id as String (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'tool_call_id'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call",
            sa.Column("tool_call_id", sa.String(), nullable=False, server_default=""),
        )

    # Add reasoning_tokens (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'reasoning_tokens'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call", sa.Column("reasoning_tokens", sa.Text(), nullable=True)
        )

    # Rename tool_arguments to tool_call_arguments (if not already done)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'tool_arguments'
    """
        )
    )
    if result.fetchone():
        op.alter_column(
            "tool_call", "tool_arguments", new_column_name="tool_call_arguments"
        )

    # Rename tool_result to tool_call_response (if not already done)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'tool_result'
    """
        )
    )
    if result.fetchone():
        op.alter_column(
            "tool_call", "tool_result", new_column_name="tool_call_response"
        )

    # Add tool_call_tokens (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'tool_call_tokens'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "tool_call",
            sa.Column(
                "tool_call_tokens", sa.Integer(), nullable=False, server_default="0"
            ),
        )

    # Drop tool_name column (if exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tool_call' AND column_name = 'tool_name'
    """
        )
    )
    if result.fetchone():
        op.drop_column("tool_call", "tool_name")

    # Add replace_base_system_prompt to persona table (if not exists)
    result = conn.execute(
        sa.text(
            """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'replace_base_system_prompt'
    """
        )
    )
    if not result.fetchone():
        op.add_column(
            "persona",
            sa.Column(
                "replace_base_system_prompt",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )


def downgrade() -> None:
    # Reverse persona changes
    op.drop_column("persona", "replace_base_system_prompt")

    # Reverse ToolCall changes
    op.add_column("tool_call", sa.Column("tool_name", sa.String(), nullable=False))
    op.drop_column("tool_call", "tool_id")
    op.drop_column("tool_call", "tool_call_tokens")
    op.alter_column("tool_call", "tool_call_response", new_column_name="tool_result")
    op.alter_column(
        "tool_call", "tool_call_arguments", new_column_name="tool_arguments"
    )
    op.drop_column("tool_call", "reasoning_tokens")
    op.drop_column("tool_call", "tool_call_id")
    op.drop_column("tool_call", "tab_number")
    op.drop_column("tool_call", "turn_number")
    op.drop_constraint(
        "fk_tool_call_parent_tool_call_id", "tool_call", type_="foreignkey"
    )
    op.drop_column("tool_call", "parent_tool_call_id")
    op.alter_column(
        "tool_call",
        "parent_chat_message_id",
        new_column_name="message_id",
        nullable=False,
    )
    op.drop_constraint("fk_tool_call_chat_session_id", "tool_call", type_="foreignkey")
    op.drop_column("tool_call", "chat_session_id")

    op.add_column(
        "chat_message",
        sa.Column(
            "research_answer_purpose",
            sa.Enum("INTRO", "DEEP_DIVE", name="researchanswerpurpose"),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_message", sa.Column("research_plan", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "research_type",
            sa.Enum("SIMPLE", "DEEP", name="researchtype"),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("refined_answer_improvement", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column("is_agentic", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "chat_message", sa.Column("overridden_model", sa.String(), nullable=True)
    )
    op.add_column(
        "chat_message", sa.Column("alternate_assistant_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "chat_message", sa.Column("rephrased_query", sa.Text(), nullable=True)
    )
    op.drop_column("chat_message", "reasoning_tokens")
    op.drop_constraint(
        "fk_chat_message_latest_child_message_id", "chat_message", type_="foreignkey"
    )
    op.alter_column(
        "chat_message",
        "latest_child_message_id",
        new_column_name="latest_child_message",
    )
    op.drop_constraint(
        "fk_chat_message_parent_message_id", "chat_message", type_="foreignkey"
    )
    op.alter_column(
        "chat_message", "parent_message_id", new_column_name="parent_message"
    )

    # Recreate agent sub question and sub query tables
    op.create_table(
        "agent__sub_question",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("primary_question_id", sa.Integer(), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sub_question", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("level_question_num", sa.Integer(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sub_answer", sa.Text(), nullable=False),
        sa.Column("sub_question_doc_results", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["primary_question_id"], ["chat_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["chat_session_id"], ["chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent__sub_query",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_question_id", sa.Integer(), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sub_query", sa.Text(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_question_id"], ["agent__sub_question.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["chat_session_id"], ["chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent__sub_query__search_doc",
        sa.Column("sub_query_id", sa.Integer(), nullable=False),
        sa.Column("search_doc_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sub_query_id"], ["agent__sub_query.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["search_doc_id"], ["search_doc.id"]),
        sa.PrimaryKeyConstraint("sub_query_id", "search_doc_id"),
    )

    # Recreate research agent tables
    op.create_table(
        "research_agent_iteration",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("primary_question_id", sa.Integer(), nullable=False),
        sa.Column("iteration_nr", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("reasoning", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["primary_question_id"], ["chat_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "primary_question_id",
            "iteration_nr",
            name="_research_agent_iteration_unique_constraint",
        ),
    )

    op.create_table(
        "research_agent_iteration_sub_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("primary_question_id", sa.Integer(), nullable=False),
        sa.Column("iteration_nr", sa.Integer(), nullable=False),
        sa.Column("iteration_sub_step_nr", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sub_step_instructions", sa.String(), nullable=True),
        sa.Column("sub_step_tool_id", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.String(), nullable=True),
        sa.Column("sub_answer", sa.String(), nullable=True),
        sa.Column("cited_doc_results", postgresql.JSONB(), nullable=False),
        sa.Column("claims", postgresql.JSONB(), nullable=True),
        sa.Column("is_web_fetch", sa.Boolean(), nullable=True),
        sa.Column("queries", postgresql.JSONB(), nullable=True),
        sa.Column("generated_images", postgresql.JSONB(), nullable=True),
        sa.Column("additional_data", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["primary_question_id", "iteration_nr"],
            [
                "research_agent_iteration.primary_question_id",
                "research_agent_iteration.iteration_nr",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["sub_step_tool_id"], ["tool.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
