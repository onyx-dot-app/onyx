"""add enterprise and name fields to scim_user_mapping

Revision ID: 7616121f6e97
Revises: 07b98176f1de
Create Date: 2026-02-23 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7616121f6e97"
down_revision = "07b98176f1de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scim_user_mapping",
        sa.Column("department", sa.String(), nullable=True),
    )
    op.add_column(
        "scim_user_mapping",
        sa.Column("manager", sa.String(), nullable=True),
    )
    op.add_column(
        "scim_user_mapping",
        sa.Column("given_name", sa.String(), nullable=True),
    )
    op.add_column(
        "scim_user_mapping",
        sa.Column("family_name", sa.String(), nullable=True),
    )
    op.add_column(
        "scim_user_mapping",
        sa.Column("scim_emails_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scim_user_mapping", "scim_emails_json")
    op.drop_column("scim_user_mapping", "family_name")
    op.drop_column("scim_user_mapping", "given_name")
    op.drop_column("scim_user_mapping", "manager")
    op.drop_column("scim_user_mapping", "department")
