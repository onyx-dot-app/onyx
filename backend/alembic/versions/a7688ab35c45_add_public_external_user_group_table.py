"""Add public_external_user_group table

Revision ID: a7688ab35c45
Revises: 5c448911b12f
Create Date: 2025-05-06 20:55:12.747875

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7688ab35c45"
down_revision = "5c448911b12f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_external_user_group",
        sa.Column("external_user_group_id", sa.String(), nullable=False),
        sa.Column("cc_pair_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("external_user_group_id", "cc_pair_id"),
        sa.ForeignKeyConstraint(
            ["cc_pair_id"], ["connector_credential_pair.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("public_external_user_group")
