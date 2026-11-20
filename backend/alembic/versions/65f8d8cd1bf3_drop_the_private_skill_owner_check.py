"""drop the private skill owner check

Code no longer writes the old custom skill rows, so their sharing columns go
stale. A skill published or transferred after that keeps a private row whose
author is set to NULL when the author is deleted, and the check would refuse
the user delete.

Revision ID: 65f8d8cd1bf3
Revises: 730bce2814a0
Create Date: 2026-11-18 09:37:27.811206

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "65f8d8cd1bf3"
down_revision = "730bce2814a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_private_skill_has_owner", "skill", type_="check")


def downgrade() -> None:
    # Rows written while the check was gone can break it.
    op.create_check_constraint(
        "ck_private_skill_has_owner",
        "skill",
        "built_in_skill_id IS NOT NULL OR public_permission IS NOT NULL "
        "OR author_user_id IS NOT NULL",
        postgresql_not_valid=True,
    )
