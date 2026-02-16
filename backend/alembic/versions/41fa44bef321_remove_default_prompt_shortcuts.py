"""remove default prompt shortcuts

Revision ID: 41fa44bef321
Revises: 2c2430828bdf
Create Date: 2025-01-21

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "41fa44bef321"
down_revision = "2c2430828bdf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete any user associations for the default prompts first (foreign key constraint)
    op.execute(
        "DELETE FROM inputprompt__user WHERE input_prompt_id IN (SELECT id FROM inputprompt WHERE id < 0)"
    )
    # Delete the pre-seeded default prompt shortcuts (they have negative IDs)
    op.execute("DELETE FROM inputprompt WHERE id < 0")


def downgrade() -> None:
    # We don't restore the default prompts on downgrade
    pass
