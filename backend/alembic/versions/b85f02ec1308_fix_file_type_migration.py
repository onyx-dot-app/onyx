"""fix-file-type-migration

Revision ID: b85f02ec1308
Revises: a3bfd0d64902
Create Date: 2024-05-31 18:09:26.658164

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b85f02ec1308"
down_revision = "a3bfd0d64902"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE file_store
        SET file_origin = UPPER(file_origin)
    """
    )


def downgrade() -> None:
    # Let's not break anything on purpose :)
    pass
