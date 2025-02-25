"""add index

Revision ID: 8f43500ee275
Revises: f13db29f3101
Create Date: 2025-02-24 17:35:33.072714

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "8f43500ee275"
down_revision = "f13db29f3101"
branch_labels = None
depends_on = None


def upgrade():
    # Add a tsvector column to store the precomputed text search vector
    op.execute(
        """
        ALTER TABLE chat_message
        ADD COLUMN message_tsv tsvector;
        """
    )

    # Create a trigger to automatically update the tsvector column when message is updated
    # Use a more comprehensive approach that includes both English dictionary and simple tokenization
    op.execute(
        """
        CREATE OR REPLACE FUNCTION chat_message_trigger() RETURNS trigger AS $$
        BEGIN
            -- Combine both English dictionary and simple tokenization for better coverage
            -- This helps with short words and partial matches
            NEW.message_tsv =
                setweight(to_tsvector('english', NEW.message), 'A') ||  -- English dictionary with stemming
                setweight(to_tsvector('simple', NEW.message), 'B');     -- Simple tokenization without stopwords
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER chat_message_update_trigger
        BEFORE INSERT OR UPDATE ON chat_message
        FOR EACH ROW
        EXECUTE FUNCTION chat_message_trigger();
        """
    )

    # Populate the tsvector column for existing records using the same approach
    op.execute(
        """
        UPDATE chat_message
        SET message_tsv =
            setweight(to_tsvector('english', message), 'A') ||
            setweight(to_tsvector('simple', message), 'B');
        """
    )

    # Verify the column was populated correctly
    op.execute(
        """
        DO $$
        DECLARE
            total_count INTEGER;
            populated_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO total_count FROM chat_message;
            SELECT COUNT(*) INTO populated_count FROM chat_message WHERE message_tsv IS NOT NULL;

            RAISE NOTICE 'Total chat messages: %, Messages with populated tsvector: %', total_count, populated_count;

            IF populated_count < total_count THEN
                RAISE WARNING 'Not all chat messages have their message_tsv column populated!';

                -- Try to populate again for any NULL values
                UPDATE chat_message
                SET message_tsv =
                    setweight(to_tsvector('english', message), 'A') ||
                    setweight(to_tsvector('simple', message), 'B')
                WHERE message_tsv IS NULL;
            END IF;
        END $$;
        """
    )

    # Create a GIN index on the tsvector column
    op.execute(
        """
        CREATE INDEX idx_chat_message_message_tsv
        ON chat_message
        USING GIN (message_tsv);
        """
    )


def downgrade():
    # Drop the trigger
    op.execute("DROP TRIGGER IF EXISTS chat_message_update_trigger ON chat_message;")

    # Drop the trigger function
    op.execute("DROP FUNCTION IF EXISTS chat_message_trigger();")

    # Drop the index
    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_tsv;")

    # Drop the tsvector column
    op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS message_tsv;")
