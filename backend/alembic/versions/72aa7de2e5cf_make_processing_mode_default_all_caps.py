"""make processing mode default all caps

Revision ID: 72aa7de2e5cf
Revises: 2020d417ec84
Create Date: 2026-01-26 18:58:47.705253

This migration fixes the ProcessingMode enum value mismatch:
- SQLAlchemy's Enum with native_enum=False uses enum member NAMES as valid values
- The original migration stored lowercase VALUES ('regular', 'file_system')
- This converts existing data to uppercase NAMES ('REGULAR', 'FILE_SYSTEM')
- Also drops any spurious native PostgreSQL enum type that may have been auto-created
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "72aa7de2e5cf"
down_revision = "2020d417ec84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert existing lowercase values to uppercase to match enum member names
    op.execute(
        "UPDATE connector_credential_pair SET processing_mode = 'REGULAR' "
        "WHERE processing_mode = 'regular'"
    )
    op.execute(
        "UPDATE connector_credential_pair SET processing_mode = 'FILE_SYSTEM' "
        "WHERE processing_mode = 'file_system'"
    )

    # Update the server default to use uppercase
    op.alter_column(
        "connector_credential_pair",
        "processing_mode",
        server_default="REGULAR",
    )


def downgrade() -> None:
    # State prior to this was broken, so we don't want to revert back to it
    pass
