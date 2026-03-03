"""make scim_user_mapping.external_id nullable

Revision ID: a3b8d9e2f1c4
Revises: 4a1e4b1c89d2
Create Date: 2026-03-02

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a3b8d9e2f1c4"
down_revision = "4a1e4b1c89d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "scim_user_mapping",
        "external_id",
        nullable=True,
    )


def downgrade() -> None:
    # Delete any rows where external_id is NULL before re-applying NOT NULL
    scim_user_mapping = sa.table("scim_user_mapping", sa.column("external_id"))
    op.execute(
        scim_user_mapping.delete().where(scim_user_mapping.c.external_id.is_(None))
    )
    op.alter_column(
        "scim_user_mapping",
        "external_id",
        nullable=False,
    )
