"""backfill session feedback

Revision ID: 67676bcd28aa
Revises: 52fd64d0aeb2
Create Date: 2025-10-27 13:50:06.510146

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "67676bcd28aa"
down_revision = "52fd64d0aeb2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill session feedback for existing sessions
    # Uses WHERE feedback IS NULL for idempotency (safe to re-run)
    op.execute(
        """
        UPDATE chat_session cs
        SET feedback = (
            SELECT
                CASE
                    -- Mixed: at least one like AND one dislike
                    WHEN COUNT(*) FILTER (WHERE feedback = 'like') > 0
                         AND COUNT(*) FILTER (WHERE feedback = 'dislike') > 0
                    THEN 'mixed'::chatsessionfeedback

                    -- All likes (must have at least one like and zero dislikes)
                    WHEN COUNT(*) FILTER (WHERE feedback = 'like') > 0
                         AND COUNT(*) FILTER (WHERE feedback = 'dislike') = 0
                    THEN 'like'::chatsessionfeedback

                    -- All dislikes (must have at least one dislike and zero likes)
                    WHEN COUNT(*) FILTER (WHERE feedback = 'dislike') > 0
                         AND COUNT(*) FILTER (WHERE feedback = 'like') = 0
                    THEN 'dislike'::chatsessionfeedback

                    -- No feedback
                    ELSE NULL
                END
            FROM (
                -- Only count the LATEST feedback per message (users can change feedback)
                SELECT DISTINCT ON (chat_message_id)
                    chat_message_id,
                    feedback
                FROM chat_feedback
                WHERE chat_message_id IN (
                    SELECT id
                    FROM chat_message
                    WHERE chat_session_id = cs.id
                )
                AND feedback IS NOT NULL
                ORDER BY chat_message_id, id DESC
            ) latest_feedback
        )
        WHERE cs.feedback IS NULL;
    """
    )


def downgrade() -> None:
    # Set all feedback back to NULL
    # Note: This will cause temporary performance degradation (fallback to computed feedback)
    # but is safe and reversible
    op.execute(
        """
        UPDATE chat_session
        SET feedback = NULL;
    """
    )
