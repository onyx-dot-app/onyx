"""Add foreign key to user__external_user_group_id

Revision ID: 238b84885828
Revises: a7688ab35c45
Create Date: 2025-05-19 17:15:33.424584

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "238b84885828"
down_revision = "a7688ab35c45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First, clean up any entries that don't have a valid cc_pair_id
    op.execute(
        """
        DELETE FROM user__external_user_group_id
        WHERE cc_pair_id NOT IN (SELECT id FROM connector_credential_pair)
        """
    )

    # Add foreign key constraint with cascade delete
    op.create_foreign_key(
        "fk_user__external_user_group_id_cc_pair_id",
        "user__external_user_group_id",
        "connector_credential_pair",
        ["cc_pair_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop the foreign key constraint
    op.drop_constraint(
        "fk_user__external_user_group_id_cc_pair_id",
        "user__external_user_group_id",
        type_="foreignkey",
    )
