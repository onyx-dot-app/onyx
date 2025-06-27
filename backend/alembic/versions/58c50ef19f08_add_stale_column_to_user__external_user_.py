"""add stale column to external user group tables

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
    # Add the stale column with default value False to user__external_user_group_id
    op.add_column(
        "user__external_user_group_id",
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create index for efficient querying of stale rows by cc_pair_id
    op.create_index(
        "ix_user__external_user_group_id_cc_pair_id_stale",
        "user__external_user_group_id",
        ["cc_pair_id", "stale"],
        unique=False,
    )

    # Create index for efficient querying of all stale rows
    op.create_index(
        "ix_user__external_user_group_id_stale",
        "user__external_user_group_id",
        ["stale"],
        unique=False,
    )

    # Add the stale column with default value False to public_external_user_group
    op.add_column(
        "public_external_user_group",
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create index for efficient querying of stale rows by cc_pair_id
    op.create_index(
        "ix_public_external_user_group_cc_pair_id_stale",
        "public_external_user_group",
        ["cc_pair_id", "stale"],
        unique=False,
    )

    # Create index for efficient querying of all stale rows
    op.create_index(
        "ix_public_external_user_group_stale",
        "public_external_user_group",
        ["stale"],
        unique=False,
    )


def downgrade() -> None:
    # Drop the indices for public_external_user_group first
    op.drop_index(
        "ix_public_external_user_group_stale", table_name="public_external_user_group"
    )
    op.drop_index(
        "ix_public_external_user_group_cc_pair_id_stale",
        table_name="public_external_user_group",
    )

    # Drop the stale column from public_external_user_group
    op.drop_column("public_external_user_group", "stale")

    # Drop the indices for user__external_user_group_id
    op.drop_index(
        "ix_user__external_user_group_id_stale",
        table_name="user__external_user_group_id",
    )
    op.drop_index(
        "ix_user__external_user_group_id_cc_pair_id_stale",
        table_name="user__external_user_group_id",
    )

    # Drop the stale column from user__external_user_group_id
    op.drop_column("user__external_user_group_id", "stale")
