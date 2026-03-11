"""add persona scoped input prompts

Revision ID: c2f6a1d9e4b7
Revises: b5c4d7e8f9a1
Create Date: 2026-03-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2f6a1d9e4b7"
down_revision = "b5c4d7e8f9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inputprompt", sa.Column("persona_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inputprompt_persona_id_persona",
        "inputprompt",
        "persona",
        ["persona_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_unique_constraint(
        "uq_inputprompt_prompt_persona_id",
        "inputprompt",
        ["prompt", "persona_id"],
    )

    op.drop_index("uq_inputprompt_prompt_public", table_name="inputprompt")
    op.create_index(
        "uq_inputprompt_prompt_public",
        "inputprompt",
        ["prompt"],
        unique=True,
        postgresql_where=sa.text(
            "is_public = TRUE AND user_id IS NULL AND persona_id IS NULL"
        ),
    )

    op.create_check_constraint(
        "ck_inputprompt_only_one_owner",
        "inputprompt",
        "(user_id IS NULL) OR (persona_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_inputprompt_public_has_no_owner",
        "inputprompt",
        "(is_public = FALSE) OR (user_id IS NULL AND persona_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inputprompt_public_has_no_owner", "inputprompt")
    op.drop_constraint("ck_inputprompt_only_one_owner", "inputprompt")

    # Persona-scoped prompts are not representable in the pre-migration schema.
    # Remove them before restoring legacy uniqueness on prompt where user_id IS NULL,
    # otherwise rollback can fail when different personas share shortcut names.
    op.execute("DELETE FROM inputprompt WHERE persona_id IS NOT NULL")

    op.drop_index("uq_inputprompt_prompt_public", table_name="inputprompt")
    op.create_index(
        "uq_inputprompt_prompt_public",
        "inputprompt",
        ["prompt"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )

    op.drop_constraint(
        "uq_inputprompt_prompt_persona_id", "inputprompt", type_="unique"
    )
    op.drop_constraint(
        "fk_inputprompt_persona_id_persona", "inputprompt", type_="foreignkey"
    )
    op.drop_column("inputprompt", "persona_id")
