"""foreign key input prompts

Revision ID: 33ea50e88f24
Revises: a6df6b88ef81
Create Date: 2025-01-29 10:54:22.141765

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "33ea50e88f24"
down_revision = "a6df6b88ef81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safely drop constraints if exists
    op.execute(
        """
        ALTER TABLE inputprompt__user
        DROP CONSTRAINT IF EXISTS inputprompt__user_input_prompt_id_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE inputprompt__user
        DROP CONSTRAINT IF EXISTS inputprompt__user_user_id_fkey
        """
    )

    # Recreate with ON DELETE CASCADE
    op.create_foreign_key(
        "inputprompt__user_input_prompt_id_fkey",
        "inputprompt__user",
        "inputprompt",
        ["input_prompt_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        "inputprompt__user_user_id_fkey",
        "inputprompt__user",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop the new FKs with ondelete
    op.drop_constraint(
        "inputprompt__user_input_prompt_id_fkey",
        "inputprompt__user",
        type_="foreignkey",
    )
    op.drop_constraint(
        "inputprompt__user_user_id_fkey",
        "inputprompt__user",
        type_="foreignkey",
    )

    # Recreate them without cascading
    op.create_foreign_key(
        "inputprompt__user_input_prompt_id_fkey",
        "inputprompt__user",
        "inputprompt",
        ["input_prompt_id"],
        ["id"],
    )
    op.create_foreign_key(
        "inputprompt__user_user_id_fkey",
        "inputprompt__user",
        "user",
        ["user_id"],
        ["id"],
    )
