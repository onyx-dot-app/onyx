"""add stale column to user__external_user_group_id

Revision ID: 58c50ef19f08
Revises: 7b9b952abdf6
Create Date: 2025-06-25 14:08:14.162380

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "58c50ef19f08"
down_revision = "7b9b952abdf6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the stale column with default value False
    op.add_column(
        "user__external_user_group_id",
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create index for efficient querying of stale rows by cc_pair_id
    op.create_index(
        "ix_user_external_group_cc_pair_stale",
        "user__external_user_group_id",
        ["cc_pair_id", "stale"],
        unique=False,
    )

    # Create index for efficient querying of all stale rows
    op.create_index(
        "ix_user_external_group_stale",
        "user__external_user_group_id",
        ["stale"],
        unique=False,
    )


def downgrade() -> None:
    # Drop the indices first
    op.drop_index(
        "ix_user_external_group_stale", table_name="user__external_user_group_id"
    )
    op.drop_index(
        "ix_user_external_group_cc_pair_stale",
        table_name="user__external_user_group_id",
    )

    # Drop the stale column
    op.drop_column("user__external_user_group_id", "stale")
