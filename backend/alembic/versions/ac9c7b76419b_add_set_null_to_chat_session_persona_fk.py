"""Add SET NULL cascade to chat_session.persona_id foreign key

Revision ID: ac9c7b76419b
Revises: 73e9983e5091
Create Date: 2026-01-17 18:10:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "ac9c7b76419b"
down_revision = "73e9983e5091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint (no cascade behavior)
    op.drop_constraint("fk_chat_session_persona_id", "chat_session", type_="foreignkey")
    # Recreate with SET NULL on delete, so deleting a persona sets
    # chat_session.persona_id to NULL instead of blocking the delete
    op.create_foreign_key(
        "fk_chat_session_persona_id",
        "chat_session",
        "persona",
        ["persona_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Revert to original constraint without cascade behavior
    op.drop_constraint("fk_chat_session_persona_id", "chat_session", type_="foreignkey")
    op.create_foreign_key(
        "fk_chat_session_persona_id",
        "chat_session",
        "persona",
        ["persona_id"],
        ["id"],
    )
