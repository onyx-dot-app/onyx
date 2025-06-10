"""Chat Reworked

Revision ID: b156fa702355
Revises: baf71f781b9e
Create Date: 2023-12-12 00:57:41.823371

"""

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM
from onyx.configs.constants import DocumentSource

# revision identifiers, used by Alembic.
revision = "b156fa702355"
down_revision = "baf71f781b9e"
branch_labels: None = None
depends_on: None = None


searchtype_enum = ENUM(
    "KEYWORD", "SEMANTIC", "HYBRID", name="searchtype", create_type=True
)
recencybiassetting_enum = ENUM(
    "FAVOR_RECENT",
    "BASE_DECAY",
    "NO_DECAY",
    "AUTO",
    name="recencybiassetting",
    create_type=True,
)


def upgrade() -> None:
    bind = op.get_bind()
    searchtype_enum.create(bind)
    recencybiassetting_enum.create(bind)

    # This is irrecoverable, whatever
    op.execute("DELETE FROM chat_feedback")
    op.execute("DELETE FROM document_retrieval_feedback")

    op.create_table(
        "search_doc",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_ind", sa.Integer(), nullable=False),
        sa.Column("semantic_id", sa.String(), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("blurb", sa.String(), nullable=False),
        sa.Column("boost", sa.Integer(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(DocumentSource, native=False),
            nullable=False,
        ),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("match_highlights", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_owners", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("secondary_owners", postgresql.ARRAY(sa.String()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("task_prompt", sa.Text(), nullable=False),
        sa.Column("include_citations", sa.Boolean(), nullable=False),
        sa.Column("datetime_aware", sa.Boolean(), nullable=False),
        sa.Column("default_prompt", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "persona__prompt",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompt.id"],
        ),
        sa.PrimaryKeyConstraint("persona_id", "prompt_id"),
    )

    # Changes to persona first so chat_sessions can have the right persona
    # The empty persona will be overwritten on server startup
    op.add_column(
        "persona",
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
    )
    op.add_column(
        "persona",
        sa.Column(
            "search_type",
            searchtype_enum,
            nullable=True,
        ),
    )
    op.execute("UPDATE persona SET search_type = 'HYBRID'")
    op.alter_column("persona", "search_type", nullable=False)
    op.add_column(
        "persona",
        sa.Column("llm_relevance_filter", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE persona SET llm_relevance_filter = TRUE")
    op.alter_column("persona", "llm_relevance_filter", nullable=False)
    op.add_column(
        "persona",
        sa.Column("llm_filter_extraction", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE persona SET llm_filter_extraction = TRUE")
    op.alter_column("persona", "llm_filter_extraction", nullable=False)
    op.add_column(
        "persona",
        sa.Column(
            "recency_bias",
            recencybiassetting_enum,
            nullable=True,
        ),
    )
    op.execute("UPDATE persona SET recency_bias = 'BASE_DECAY'")
    op.alter_column("persona", "recency_bias", nullable=False)
    op.alter_column("persona", "description", existing_type=sa.VARCHAR(), nullable=True)
    op.execute("UPDATE persona SET description = ''")
    op.alter_column("persona", "description", nullable=False)
    op.create_foreign_key("persona__user_fk", "persona", "user", ["user_id"], ["id"])
    op.drop_column("persona", "datetime_aware")
    op.drop_column("persona", "tools")
    op.drop_column("persona", "hint_text")
    op.drop_column("persona", "apply_llm_relevance_filter")
    op.drop_column("persona", "retrieval_enabled")
    op.drop_column("persona", "system_text")

    # Need to create a persona row so fk can work
    result = bind.execute(sa.text("SELECT 1 FROM persona WHERE id = 0"))
    exists = result.fetchone()
    if not exists:
        op.execute(
            sa.text(
                """
                INSERT INTO persona (
                    id, user_id, name, description, search_type, num_chunks,
                    llm_relevance_filter, llm_filter_extraction, recency_bias,
                    llm_model_version_override, default_persona, deleted
                ) VALUES (
                    0, NULL, '', '', 'HYBRID', NULL,
                    TRUE, TRUE, 'BASE_DECAY', NULL, TRUE, FALSE
                )
                """
            )
        )
    delete_statement = sa.text(
        """
        DELETE FROM persona
        WHERE name = 'Danswer' AND default_persona = TRUE AND id != 0
        """
    )

    bind.execute(delete_statement)

    op.add_column(
        "chat_feedback",
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
    )
    op.drop_constraint(
        "chat_feedback_chat_message_chat_session_id_chat_message_me_fkey",
        "chat_feedback",
        type_="foreignkey",
    )
    op.drop_column("chat_feedback", "chat_message_edit_number")
    op.drop_column("chat_feedback", "chat_message_chat_session_id")
    op.drop_column("chat_feedback", "chat_message_message_number")
    op.add_column(
        "chat_message",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            unique=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("parent_message", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column("latest_child_message", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_message", sa.Column("rephrased_query", sa.Text(), nullable=True)
    )
    op.add_column("chat_message", sa.Column("prompt_id", sa.Integer(), nullable=True))
    op.add_column(
        "chat_message",
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("chat_message", sa.Column("error", sa.Text(), nullable=True))
    op.drop_constraint("fk_chat_message_persona_id", "chat_message", type_="foreignkey")
    op.create_foreign_key(
        "chat_message__prompt_fk", "chat_message", "prompt", ["prompt_id"], ["id"]
    )
    op.drop_column("chat_message", "parent_edit_number")
    op.drop_column("chat_message", "persona_id")
    op.drop_column("chat_message", "reference_docs")
    op.drop_column("chat_message", "edit_number")
    op.drop_column("chat_message", "latest")
    op.drop_column("chat_message", "message_number")
    op.add_column("chat_session", sa.Column("one_shot", sa.Boolean(), nullable=True))
    op.execute("UPDATE chat_session SET one_shot = TRUE")
    op.alter_column("chat_session", "one_shot", nullable=False)
    op.alter_column(
        "chat_session",
        "persona_id",
        existing_type=sa.INTEGER(),
        nullable=True,
    )
    op.execute("UPDATE chat_session SET persona_id = 0")
    op.alter_column("chat_session", "persona_id", nullable=False)
    op.add_column(
        "document_retrieval_feedback",
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
    )
    op.drop_constraint(
        "document_retrieval_feedback_qa_event_id_fkey",
        "document_retrieval_feedback",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "document_retrieval_feedback__chat_message_fk",
        "document_retrieval_feedback",
        "chat_message",
        ["chat_message_id"],
        ["id"],
    )
    op.drop_column("document_retrieval_feedback", "qa_event_id")

    # Relation table must be created after the other tables are correct
    op.create_table(
        "chat_message__search_doc",
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
        sa.Column("search_doc_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_message.id"],
        ),
        sa.ForeignKeyConstraint(
            ["search_doc_id"],
            ["search_doc.id"],
        ),
        sa.PrimaryKeyConstraint("chat_message_id", "search_doc_id"),
    )

    # Needs to be created after chat_message id field is added
    op.create_foreign_key(
        "chat_feedback__chat_message_fk",
        "chat_feedback",
        "chat_message",
        ["chat_message_id"],
        ["id"],
    )

    op.drop_table("query_event")


def downgrade() -> None:
    # NOTE: you will lose all chat history. This is to satisfy the non-nullable constraints
    # below
    op.execute("DELETE FROM chat_feedback")
    op.execute("DELETE FROM chat_message__search_doc")
    op.execute("DELETE FROM document_retrieval_feedback")
    op.execute("DELETE FROM document_retrieval_feedback")
    op.execute("DELETE FROM chat_message")
    op.execute("DELETE FROM chat_session")

    op.drop_constraint(
        "chat_feedback__chat_message_fk", "chat_feedback", type_="foreignkey"
    )
    op.drop_constraint(
        "document_retrieval_feedback__chat_message_fk",
        "document_retrieval_feedback",
        type_="foreignkey",
    )
    op.drop_constraint("persona__user_fk", "persona", type_="foreignkey")
    op.drop_constraint("chat_message__prompt_fk", "chat_message", type_="foreignkey")
    op.drop_constraint(
        "chat_message__search_doc_chat_message_id_fkey",
        "chat_message__search_doc",
        type_="foreignkey",
    )
    op.add_column(
        "persona",
        sa.Column("system_text", sa.TEXT(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column(
            "retrieval_enabled",
            sa.BOOLEAN(),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.execute("UPDATE persona SET retrieval_enabled = TRUE")
    op.alter_column("persona", "retrieval_enabled", nullable=False)
    op.add_column(
        "persona",
        sa.Column(
            "apply_llm_relevance_filter",
            sa.BOOLEAN(),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "persona",
        sa.Column("hint_text", sa.TEXT(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column(
            "tools",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "persona",
        sa.Column("datetime_aware", sa.BOOLEAN(), autoincrement=False, nullable=True),
    )
    op.execute("UPDATE persona SET datetime_aware = TRUE")
    op.alter_column("persona", "datetime_aware", nullable=False)
    op.alter_column("persona", "description", existing_type=sa.VARCHAR(), nullable=True)
    op.drop_column("persona", "recency_bias")
    op.drop_column("persona", "llm_filter_extraction")
    op.drop_column("persona", "llm_relevance_filter")
    op.drop_column("persona", "search_type")
    op.drop_column("persona", "user_id")
    op.add_column(
        "document_retrieval_feedback",
        sa.Column("qa_event_id", sa.INTEGER(), autoincrement=False, nullable=False),
    )
    op.drop_column("document_retrieval_feedback", "chat_message_id")
    op.alter_column(
        "chat_session", "persona_id", existing_type=sa.INTEGER(), nullable=True
    )
    op.drop_column("chat_session", "one_shot")
    op.add_column(
        "chat_message",
        sa.Column(
            "message_number",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
            primary_key=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("latest", sa.BOOLEAN(), autoincrement=False, nullable=False),
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "edit_number",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
            primary_key=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "reference_docs",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("persona_id", sa.INTEGER(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "parent_edit_number",
            sa.INTEGER(),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_chat_message_persona_id",
        "chat_message",
        "persona",
        ["persona_id"],
        ["id"],
    )
    op.drop_column("chat_message", "error")
    op.drop_column("chat_message", "citations")
    op.drop_column("chat_message", "prompt_id")
    op.drop_column("chat_message", "rephrased_query")
    op.drop_column("chat_message", "latest_child_message")
    op.drop_column("chat_message", "parent_message")
    op.drop_column("chat_message", "id")
    op.add_column(
        "chat_feedback",
        sa.Column(
            "chat_message_message_number",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.add_column(
        "chat_feedback",
        sa.Column(
            "chat_message_chat_session_id",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
            primary_key=True,
        ),
    )
    op.add_column(
        "chat_feedback",
        sa.Column(
            "chat_message_edit_number",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.drop_column("chat_feedback", "chat_message_id")
    op.create_table(
        "query_event",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("query", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column(
            "selected_search_flow",
            sa.VARCHAR(),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("llm_answer", sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column("feedback", sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column("user_id", sa.UUID(), autoincrement=False, nullable=True),
        sa.Column(
            "time_created",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "retrieved_document_ids",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("chat_session_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_session.id"],
            name="fk_query_event_chat_session_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="query_event_user_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="query_event_pkey"),
    )
    op.drop_table("chat_message__search_doc")
    op.drop_table("persona__prompt")
    op.drop_table("prompt")
    op.drop_table("search_doc")
    op.create_unique_constraint(
        "uq_chat_message_combination",
        "chat_message",
        ["chat_session_id", "message_number", "edit_number"],
    )
    op.create_foreign_key(
        "chat_feedback_chat_message_chat_session_id_chat_message_me_fkey",
        "chat_feedback",
        "chat_message",
        [
            "chat_message_chat_session_id",
            "chat_message_message_number",
            "chat_message_edit_number",
        ],
        ["chat_session_id", "message_number", "edit_number"],
    )
    op.create_foreign_key(
        "document_retrieval_feedback_qa_event_id_fkey",
        "document_retrieval_feedback",
        "query_event",
        ["qa_event_id"],
        ["id"],
    )

    op.execute("DROP TYPE IF EXISTS searchtype")
    op.execute("DROP TYPE IF EXISTS recencybiassetting")
    op.execute("DROP TYPE IF EXISTS documentsource")
