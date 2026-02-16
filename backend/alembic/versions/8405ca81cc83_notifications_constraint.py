"""notifications constraint, sort index, and cleanup old notifications

Revision ID: 8405ca81cc83
Revises: a3c1a7904cd0
Create Date: 2026-01-07 16:43:44.855156

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "8405ca81cc83"
down_revision = "a3c1a7904cd0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create unique index for notification deduplication.
    # This enables atomic ON CONFLICT DO NOTHING inserts in batch_create_notifications.
    #
    # Uses COALESCE to handle NULL additional_data (NULLs are normally distinct
    # in unique constraints, but we want NULL == NULL for deduplication).
    # The '{}' represents an empty JSONB object as the NULL replacement.

    # Clean up legacy notifications first
    op.execute("DELETE FROM notification WHERE title = 'New Notification'")

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_notification_user_type_data
        ON notification (user_id, notif_type, COALESCE(additional_data, '{}'::jsonb))
        """
    )

    # Create index for efficient notification sorting by user
    # Covers: WHERE user_id = ? ORDER BY dismissed, first_shown DESC
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_notification_user_sort
        ON notification (user_id, dismissed, first_shown DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notification_user_type_data")
    op.execute("DROP INDEX IF EXISTS ix_notification_user_sort")
