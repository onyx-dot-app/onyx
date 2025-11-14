"""add switchover_type field and remove background_reindex_enabled

Revision ID: 2acdef638fc2
Revises: a4f23d6b71c8
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.enums import SwitchoverType


# revision identifiers, used by Alembic.
revision = "2acdef638fc2"
down_revision = "a4f23d6b71c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add switchover_type column with default value of REINDEX
    op.add_column(
        "search_settings",
        sa.Column(
            "switchover_type",
            sa.Enum(SwitchoverType, native_enum=False),
            nullable=False,
            server_default=SwitchoverType.REINDEX.value,
        ),
    )

    # Migrate existing data: set switchover_type based on background_reindex_enabled
    # REINDEX where background_reindex_enabled=True, INSTANT where False
    op.execute(
        """
        UPDATE search_settings
        SET switchover_type = CASE
            WHEN background_reindex_enabled = true THEN 'REINDEX'
            ELSE 'INSTANT'
        END
        """
    )

    # Remove the background_reindex_enabled column (replaced by switchover_type)
    op.drop_column("search_settings", "background_reindex_enabled")


def downgrade() -> None:
    # Re-add the background_reindex_enabled column with default value of True
    op.add_column(
        "search_settings",
        sa.Column(
            "background_reindex_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    # Set background_reindex_enabled based on switchover_type
    op.execute(
        """
        UPDATE search_settings
        SET background_reindex_enabled = CASE
            WHEN switchover_type = 'INSTANT' THEN false
            ELSE true
        END
        """
    )
    # Remove the switchover_type column
    op.drop_column("search_settings", "switchover_type")
