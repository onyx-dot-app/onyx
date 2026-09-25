"""add user_group__cc_pair_data_access

Revision ID: ac05f4a21dbd
Revises: df879de08494
Create Date: 2026-09-23 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ac05f4a21dbd"
down_revision = "df879de08494"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_group__cc_pair_data_access",
        sa.Column(
            "cc_pair_id",
            sa.Integer(),
            sa.ForeignKey("connector_credential_pair.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_user_group__cc_pair_data_access_user_group_id",
        "user_group__cc_pair_data_access",
        ["user_group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_group__cc_pair_data_access_user_group_id",
        table_name="user_group__cc_pair_data_access",
    )
    op.drop_table("user_group__cc_pair_data_access")
