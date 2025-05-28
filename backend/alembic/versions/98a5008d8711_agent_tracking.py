"""agent_tracking

Revision ID: 98a5008d8711
Revises: 2f80c6a2550f
Create Date: 2025-01-29 17:00:00.000001

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "98a5008d8711"
down_revision = "2f80c6a2550f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent__search_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_duration_s", sa.Float(), nullable=False),
        sa.Column("full_duration_s", sa.Float(), nullable=False),
        sa.Column("base_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("refined_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("all_metrics", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create sub_question table
    op.create_table(
        "agent__sub_question",
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
        sa.Column("sub_question_doc_results", postgresql.JSONB(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("level_question_num", sa.Integer(), nullable=False),
    )

    # Create sub_query table
    op.create_table(
        "agent__sub_query",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "parent_question_id", sa.Integer, sa.ForeignKey("agent__sub_question.id")
        ),
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
        "agent__sub_query__search_doc",
        sa.Column(
            "sub_query_id",
            sa.Integer,
            sa.ForeignKey("agent__sub_query.id"),
            primary_key=True,
        ),
        sa.Column(
            "search_doc_id",
            sa.Integer,
            sa.ForeignKey("search_doc.id"),
            primary_key=True,
        ),
    )

    op.add_column(
        "chat_message",
        sa.Column(
            "refined_answer_improvement",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "refined_answer_improvement")
    op.drop_table("agent__sub_query__search_doc")
    op.drop_table("agent__sub_query")
    op.drop_table("agent__sub_question")
    op.drop_table("agent__search_metrics")
