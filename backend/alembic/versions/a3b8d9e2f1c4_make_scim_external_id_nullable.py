"""make scim_user_mapping.external_id nullable

Revision ID: a3b8d9e2f1c4
Revises: 2664261bfaab
Create Date: 2026-03-02

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b8d9e2f1c4"
down_revision = "2664261bfaab"
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
    op.execute("DELETE FROM scim_user_mapping WHERE external_id IS NULL")
    op.alter_column(
        "scim_user_mapping",
        "external_id",
        nullable=False,
    )
