"""Pause finished user file connectors

Revision ID: b558f51620b4
Revises: 90e3b9af7da4
Create Date: 2025-08-15 17:17:02.456704

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b558f51620b4"
down_revision = "90e3b9af7da4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set all user file connector credential pairs with ACTIVE status to PAUSED
    # This ensures user files don't continue to run indexing tasks after processing
    op.execute(
        """
        UPDATE connector_credential_pair
        SET status = 'PAUSED'
        WHERE is_user_file = true
        AND status = 'ACTIVE'
        """
    )


def downgrade() -> None:
    pass
