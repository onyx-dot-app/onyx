"""New Chat History

Revision ID: a852cbe15577
Revises: 6436661d5b65
Create Date: 2025-11-08 15:16:37.781308

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a852cbe15577"
down_revision = "6436661d5b65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop old research/agent tables (CASCADE handles dependencies)
    op.execute("DROP TABLE IF EXISTS research_agent_iteration_sub_step CASCADE")
    op.execute("DROP TABLE IF EXISTS research_agent_iteration CASCADE")
    op.execute("DROP TABLE IF EXISTS agent__sub_query__search_doc CASCADE")
    op.execute("DROP TABLE IF EXISTS agent__sub_query CASCADE")
    op.execute("DROP TABLE IF EXISTS agent__sub_question CASCADE")

    # 2. ChatMessage table changes
    # Rename columns and add FKs
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

    # Add new column
    op.add_column(
        "chat_message", sa.Column("reasoning_tokens", sa.Text(), nullable=True)
    )

    # Drop old columns
    op.drop_column("chat_message", "rephrased_query")
    op.drop_column("chat_message", "alternate_assistant_id")
    op.drop_column("chat_message", "overridden_model")
    op.drop_column("chat_message", "is_agentic")
    op.drop_column("chat_message", "refined_answer_improvement")
    op.drop_column("chat_message", "research_type")
    op.drop_column("chat_message", "research_plan")
    op.drop_column("chat_message", "research_answer_purpose")

    # 3. ToolCall table changes
    # Drop the unique constraint first
    op.drop_constraint("uq_tool_call_message_id", "tool_call", type_="unique")

    # Delete orphaned tool_call rows (those without valid chat_message)
    op.execute(
        "DELETE FROM tool_call WHERE message_id NOT IN (SELECT id FROM chat_message)"
    )

    # Add chat_session_id as nullable first, populate, then make NOT NULL
    op.add_column(
        "tool_call",
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Populate chat_session_id from the related chat_message
    op.execute(
        """
        UPDATE tool_call
        SET chat_session_id = chat_message.chat_session_id
        FROM chat_message
        WHERE tool_call.message_id = chat_message.id
    """
    )

    # Now make it NOT NULL and add FK
    op.alter_column("tool_call", "chat_session_id", nullable=False)
    op.create_foreign_key(
        "fk_tool_call_chat_session_id",
        "tool_call",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Rename message_id and make nullable, recreate FK with CASCADE
    op.drop_constraint("tool_call_message_id_fkey", "tool_call", type_="foreignkey")
    op.alter_column(
        "tool_call",
        "message_id",
        new_column_name="parent_chat_message_id",
        nullable=True,
    )
    op.create_foreign_key(
        "fk_tool_call_parent_chat_message_id",
        "tool_call",
        "chat_message",
        ["parent_chat_message_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add parent_tool_call_id with FK
    op.add_column(
        "tool_call", sa.Column("parent_tool_call_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_tool_call_parent_tool_call_id",
        "tool_call",
        "tool_call",
        ["parent_tool_call_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add other new columns
    op.add_column(
        "tool_call",
        sa.Column("turn_number", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tool_call",
        sa.Column("tool_call_id", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("tool_call", sa.Column("reasoning_tokens", sa.Text(), nullable=True))
    op.add_column(
        "tool_call",
        sa.Column("tool_call_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tool_call",
        sa.Column("generated_images", postgresql.JSONB(), nullable=True),
    )

    # Rename columns
    op.alter_column(
        "tool_call", "tool_arguments", new_column_name="tool_call_arguments"
    )
    op.alter_column("tool_call", "tool_result", new_column_name="tool_call_response")

    # Change tool_call_response type from JSONB to Text
    op.execute(
        """
        ALTER TABLE tool_call
        ALTER COLUMN tool_call_response TYPE TEXT
        USING tool_call_response::text
    """
    )

    # Drop old columns
    op.drop_column("tool_call", "tool_name")

    # 4. Create new association table
    op.create_table(
        "tool_call__search_doc",
        sa.Column("tool_call_id", sa.Integer(), nullable=False),
        sa.Column("search_doc_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_call.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["search_doc_id"], ["search_doc.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tool_call_id", "search_doc_id"),
    )

    # 5. Persona table change
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

    # Drop new association table
    op.drop_table("tool_call__search_doc")

    # Reverse ToolCall changes
    op.add_column(
        "tool_call",
        sa.Column("tool_name", sa.String(), nullable=False, server_default=""),
    )

    # Change tool_call_response back to JSONB
    op.execute(
        """
        ALTER TABLE tool_call
        ALTER COLUMN tool_call_response TYPE JSONB
        USING tool_call_response::jsonb
    """
    )

    op.alter_column("tool_call", "tool_call_response", new_column_name="tool_result")
    op.alter_column(
        "tool_call", "tool_call_arguments", new_column_name="tool_arguments"
    )

    op.drop_column("tool_call", "generated_images")
    op.drop_column("tool_call", "tool_call_tokens")
    op.drop_column("tool_call", "reasoning_tokens")
    op.drop_column("tool_call", "tool_call_id")
    op.drop_column("tool_call", "turn_number")

    op.drop_constraint(
        "fk_tool_call_parent_tool_call_id", "tool_call", type_="foreignkey"
    )
    op.drop_column("tool_call", "parent_tool_call_id")

    op.drop_constraint(
        "fk_tool_call_parent_chat_message_id", "tool_call", type_="foreignkey"
    )
    op.alter_column(
        "tool_call",
        "parent_chat_message_id",
        new_column_name="message_id",
        nullable=False,
    )
    op.create_foreign_key(
        "tool_call_message_id_fkey",
        "tool_call",
        "chat_message",
        ["message_id"],
        ["id"],
    )

    op.drop_constraint("fk_tool_call_chat_session_id", "tool_call", type_="foreignkey")
    op.drop_column("tool_call", "chat_session_id")

    op.create_unique_constraint("uq_tool_call_message_id", "tool_call", ["message_id"])

    # Reverse ChatMessage changes
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
        sa.Column("file_ids", postgresql.JSONB(), nullable=True),
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
