"""create pro search persistence tables

Revision ID: e9cf2bd7baed
Revises: 98a5008d8711
Create Date: 2025-01-02 17:55:56.544246

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "e9cf2bd7baed"
down_revision = "98a5008d8711"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create sub_question table
    op.create_table(
        "sub_question",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("primary_question_id", sa.Integer, sa.ForeignKey("chat_message.id")),
        sa.Column(
            "chat_session_id", UUID(as_uuid=True), sa.ForeignKey("chat_session.id")
        ),
        sa.Column("sub_question", sa.Text),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("sub_answer", sa.Text),
    )

    # Create sub_query table
    op.create_table(
        "sub_query",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_question_id", sa.Integer, sa.ForeignKey("sub_question.id")),
        sa.Column(
            "chat_session_id", UUID(as_uuid=True), sa.ForeignKey("chat_session.id")
        ),
        sa.Column("sub_query", sa.Text),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Create sub_query__search_doc association table
    op.create_table(
        "sub_query__search_doc",
        sa.Column(
            "sub_query_id", sa.Integer, sa.ForeignKey("sub_query.id"), primary_key=True
        ),
        sa.Column(
            "search_doc_id",
            sa.Integer,
            sa.ForeignKey("search_doc.id"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("sub_query__search_doc")
    op.drop_table("sub_query")
    op.drop_table("sub_question")
