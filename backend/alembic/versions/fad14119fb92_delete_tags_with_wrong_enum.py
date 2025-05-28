"""Delete Tags with wrong Enum

Revision ID: fad14119fb92
Revises: 72bdc9929a46
Create Date: 2024-04-25 17:05:09.695703

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "fad14119fb92"
down_revision = "72bdc9929a46"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Some documents may lose their tags but this is the only way as the enum
    # mapping may have changed since tag switched to string (it will be reindexed anyway)
    op.execute(
        """
        DELETE FROM document__tag
        WHERE tag_id IN (
            SELECT id FROM tag
            WHERE source ~ '^[0-9]+$'
        )
        """
    )

    op.execute(
        """
        DELETE FROM tag
        WHERE source ~ '^[0-9]+$'
        """
    )


def downgrade() -> None:
    pass
