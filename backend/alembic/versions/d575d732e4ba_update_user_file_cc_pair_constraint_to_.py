"""update_user_file_cc_pair_constraint_to_cascade

Revision ID: d575d732e4ba
Revises: cf90764725d8
Create Date: 2025-04-09 11:15:59.490947

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d575d732e4ba"
down_revision = "cf90764725d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint
    op.drop_constraint("user_file_cc_pair_id_fkey", "user_file", type_="foreignkey")

    # Recreate it with ON DELETE CASCADE
    op.create_foreign_key(
        "user_file_cc_pair_id_fkey",
        "user_file",
        "connector_credential_pair",
        ["cc_pair_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop the CASCADE constraint
    op.drop_constraint("user_file_cc_pair_id_fkey", "user_file", type_="foreignkey")

    # Recreate the original constraint without CASCADE
    op.create_foreign_key(
        "user_file_cc_pair_id_fkey",
        "user_file",
        "connector_credential_pair",
        ["cc_pair_id"],
        ["id"],
    )
