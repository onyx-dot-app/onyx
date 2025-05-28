"""Feedback Feature

Revision ID: d929f0c1c6af
Revises: 8aabb57f3b49
Create Date: 2023-08-27 13:03:54.274987

"""

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d929f0c1c6af"
down_revision = "8aabb57f3b49"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "query_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column(
            "selected_search_flow",
            sa.Enum("KEYWORD", "SEMANTIC", name="searchtype", native_enum=False),
            nullable=True,
        ),
        sa.Column("llm_answer", sa.String(), nullable=True),
        sa.Column(
            "feedback",
            sa.Enum("LIKE", "DISLIKE", name="qafeedbacktype", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "document_retrieval_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("qa_event_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_rank", sa.Integer(), nullable=False),
        sa.Column("clicked", sa.Boolean(), nullable=False),
        sa.Column(
            "feedback",
            sa.Enum(
                "ENDORSE",
                "REJECT",
                "HIDE",
                "UNHIDE",
                name="searchfeedbacktype",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
        ),
        sa.ForeignKeyConstraint(
            ["qa_event_id"],
            ["query_event.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("document", sa.Column("boost", sa.Integer(), nullable=False))
    op.add_column("document", sa.Column("hidden", sa.Boolean(), nullable=False))
    op.add_column("document", sa.Column("semantic_id", sa.String(), nullable=False))
    op.add_column("document", sa.Column("link", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("document", "link")
    op.drop_column("document", "semantic_id")
    op.drop_column("document", "hidden")
    op.drop_column("document", "boost")
    op.drop_table("document_retrieval_feedback")
    op.drop_table("query_event")
