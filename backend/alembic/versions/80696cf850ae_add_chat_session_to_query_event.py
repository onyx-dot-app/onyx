"""Add chat session to query_event

Revision ID: 80696cf850ae
Revises: 15326fcec57e
Create Date: 2023-11-26 02:38:35.008070

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "80696cf850ae"
down_revision = "15326fcec57e"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "query_event",
        sa.Column("chat_session_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_query_event_chat_session_id",
        "query_event",
        "chat_session",
        ["chat_session_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_query_event_chat_session_id", "query_event", type_="foreignkey"
    )
    op.drop_column("query_event", "chat_session_id")
