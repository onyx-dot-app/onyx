"""add session feedback trigger infrastructure

Revision ID: 52fd64d0aeb2
Revises: f3adfff20605
Create Date: 2025-10-27 13:34:05.844988

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "52fd64d0aeb2"
down_revision = "f3adfff20605"
branch_labels = None
depends_on = None

# Define the ChatSessionFeedback enum type (for session-level aggregated feedback)
chat_session_feedback_enum = postgresql.ENUM(
    "like", "dislike", "mixed", name="chatsessionfeedback", create_type=True
)


def _get_tenant_contextvar(session: Session) -> str:
    """Get the current schema for the migration"""
    current_tenant = session.execute(text("SELECT current_schema()")).scalar()
    if isinstance(current_tenant, str):
        return current_tenant
    else:
        raise ValueError("Current tenant is not a string")


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    tenant_id = _get_tenant_contextvar(session)

    # 1. Create the ChatSessionFeedback enum type in PostgreSQL
    chat_session_feedback_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add feedback column to chat_session table (nullable)
    op.add_column(
        "chat_session", sa.Column("feedback", chat_session_feedback_enum, nullable=True)
    )

    # 3. Create trigger function to maintain session feedback
    function_name = "update_chat_session_feedback"
    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION "{tenant_id}".{function_name}()
            RETURNS TRIGGER AS $$
            DECLARE
                like_count INTEGER;
                dislike_count INTEGER;
                session_id UUID;
                new_feedback chatsessionfeedback;
            BEGIN
                -- Determine which session to update
                IF TG_OP = 'DELETE' THEN
                    session_id := (
                        SELECT cm.chat_session_id
                        FROM "{tenant_id}".chat_message cm
                        WHERE cm.id = OLD.chat_message_id
                    );
                ELSE
                    session_id := (
                        SELECT cm.chat_session_id
                        FROM "{tenant_id}".chat_message cm
                        WHERE cm.id = NEW.chat_message_id
                    );
                END IF;

                -- Skip if no associated session (shouldn't happen but defensive)
                IF session_id IS NULL THEN
                    RETURN NEW;
                END IF;

                -- Count likes and dislikes for this session
                -- Only count the LATEST feedback per message (users can change feedback)
                SELECT
                    COUNT(*) FILTER (WHERE feedback = 'like'),
                    COUNT(*) FILTER (WHERE feedback = 'dislike')
                INTO like_count, dislike_count
                FROM (
                    SELECT DISTINCT ON (chat_message_id)
                        chat_message_id,
                        feedback
                    FROM "{tenant_id}".chat_feedback
                    WHERE chat_message_id IN (
                        SELECT id
                        FROM "{tenant_id}".chat_message
                        WHERE chat_session_id = session_id
                    )
                    AND feedback IS NOT NULL
                    ORDER BY chat_message_id, id DESC
                ) latest_feedback;

                -- Determine new feedback value
                IF like_count > 0 AND dislike_count > 0 THEN
                    new_feedback := 'mixed'::chatsessionfeedback;
                ELSIF like_count > 0 THEN
                    new_feedback := 'like'::chatsessionfeedback;
                ELSIF dislike_count > 0 THEN
                    new_feedback := 'dislike'::chatsessionfeedback;
                ELSE
                    new_feedback := NULL;
                END IF;

                -- Update chat_session feedback
                UPDATE "{tenant_id}".chat_session
                SET feedback = new_feedback
                WHERE id = session_id;

                -- Return appropriate record based on operation
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )

    # 4. Create trigger on chat_feedback table
    trigger_name = "chat_feedback_update_session_feedback"
    op.execute(f'DROP TRIGGER IF EXISTS {trigger_name} ON "{tenant_id}".chat_feedback')
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        AFTER INSERT OR UPDATE OR DELETE ON "{tenant_id}".chat_feedback
        FOR EACH ROW
        EXECUTE FUNCTION "{tenant_id}".{function_name}();
        """
    )

    # Note: Existing sessions will have NULL feedback until Stage 2b backfill
    # New feedback and sessions will automatically get correct values via trigger


def downgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    tenant_id = _get_tenant_contextvar(session)

    # Drop trigger and function
    op.execute(
        f'DROP TRIGGER IF EXISTS chat_feedback_update_session_feedback ON "{tenant_id}".chat_feedback'
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{tenant_id}".update_chat_session_feedback()')

    # Drop the feedback column
    op.drop_column("chat_session", "feedback")

    # Drop the enum type
    chat_session_feedback_enum.drop(op.get_bind(), checkfirst=True)
