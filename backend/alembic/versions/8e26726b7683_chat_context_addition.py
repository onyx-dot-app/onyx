"""Chat Context Addition

Revision ID: 8e26726b7683
Revises: 5809c0787398
Create Date: 2023-09-13 18:34:31.327944

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8e26726b7683"
down_revision = "5809c0787398"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "persona",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("system_text", sa.Text(), nullable=True),
        sa.Column("tools_text", sa.Text(), nullable=True),
        sa.Column("hint_text", sa.Text(), nullable=True),
        sa.Column("default_persona", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("chat_message", sa.Column("persona_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chat_message_persona_id", "chat_message", "persona", ["persona_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_message_persona_id", "chat_message", type_="foreignkey")
    op.drop_column("chat_message", "persona_id")
    op.drop_table("persona")
