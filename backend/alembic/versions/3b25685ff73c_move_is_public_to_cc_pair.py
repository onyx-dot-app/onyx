"""Move is_public to cc_pair

Revision ID: 3b25685ff73c
Revises: e0a68a81d434
Create Date: 2023-10-05 18:47:09.582849

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3b25685ff73c"
down_revision = "e0a68a81d434"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column("is_public", sa.Boolean(), nullable=True),
    )
    # fill in is_public for existing rows
    op.execute(
        "UPDATE connector_credential_pair SET is_public = true WHERE is_public IS NULL"
    )
    op.alter_column("connector_credential_pair", "is_public", nullable=False)

    op.add_column(
        "credential",
        sa.Column("is_admin", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE credential SET is_admin = true WHERE is_admin IS NULL")
    op.alter_column("credential", "is_admin", nullable=False)

    op.drop_column("credential", "public_doc")


def downgrade() -> None:
    op.add_column(
        "credential",
        sa.Column("public_doc", sa.Boolean(), nullable=True),
    )
    # setting public_doc to false for all existing rows to be safe
    # NOTE: this is likely not the correct state of the world but it's the best we can do
    op.execute("UPDATE credential SET public_doc = false WHERE public_doc IS NULL")
    op.alter_column("credential", "public_doc", nullable=False)
    op.drop_column("connector_credential_pair", "is_public")
    op.drop_column("credential", "is_admin")
