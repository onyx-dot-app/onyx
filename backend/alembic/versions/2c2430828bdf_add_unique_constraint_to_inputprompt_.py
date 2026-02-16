"""add_unique_constraint_to_inputprompt_prompt_user_id

Revision ID: 2c2430828bdf
Revises: fb80bdd256de
Create Date: 2026-01-20 16:01:54.314805

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2c2430828bdf"
down_revision = "fb80bdd256de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create unique constraint on (prompt, user_id) for user-owned prompts
    # This ensures each user can only have one shortcut with a given name
    op.create_unique_constraint(
        "uq_inputprompt_prompt_user_id",
        "inputprompt",
        ["prompt", "user_id"],
    )

    # Create partial unique index for public prompts (where user_id IS NULL)
    # PostgreSQL unique constraints don't enforce uniqueness for NULL values,
    # so we need a partial index to ensure public prompt names are also unique
    op.execute(
        """
        CREATE UNIQUE INDEX uq_inputprompt_prompt_public
        ON inputprompt (prompt)
        WHERE user_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_inputprompt_prompt_public")
    op.drop_constraint("uq_inputprompt_prompt_user_id", "inputprompt", type_="unique")
