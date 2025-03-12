"""improved index

Revision ID: 3bd4c84fe72f
Revises: 8f43500ee275
Create Date: 2025-02-26 13:07:56.217791

"""
from alembic import op
import time
import hashlib
from sqlalchemy import text

# Remove Redis import as we're not using it anymore
# from onyx.redis.redis_pool import get_redis_client
# from onyx.configs.app_configs import ALEMBIC_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "3bd4c84fe72f"
down_revision = "8f43500ee275"
branch_labels = None
depends_on = None

# Define a constant for our advisory lock
# Converting a string to a bigint for advisory lock
ALEMBIC_MIGRATION_LOCK_KEY = int(
    hashlib.md5("alembic_migration_lock".encode()).hexdigest()[:15], 16
)


# NOTE:
# This migration addresses issues with the previous migration (8f43500ee275) which caused
# an outage by creating an index without using CONCURRENTLY. This migration:
#
# 1. Creates more efficient full-text search capabilities using tsvector columns and GIN indexes
# 2. Uses CONCURRENTLY for all index creation to prevent table locking
# 3. Explicitly manages transactions with COMMIT statements to allow CONCURRENTLY to work
# (see: https://www.postgresql.org/docs/9.4/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)
# (see: https://github.com/sqlalchemy/alembic/issues/277)
# 4. Adds indexes to both chat_message and chat_session tables for comprehensive search


def upgrade() -> None:
    # Use PostgreSQL advisory locks to ensure only one migration runs at a time
    connection = op.get_bind()

    # Try to acquire an advisory lock (exclusive, session level)
    lock_acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:lock_key)").bindparams(
            lock_key=ALEMBIC_MIGRATION_LOCK_KEY
        )
    ).scalar()

    if not lock_acquired:
        raise Exception(
            "Migration already in progress by another process. Try again later."
        )

    try:
        # --- PART 1: chat_message table ---
        # Step 1: Add nullable column (quick, minimal locking)
        op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS message_tsv_gen")
        op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS message_tsv")
        op.execute("DROP TRIGGER IF EXISTS chat_message_tsv_trigger ON chat_message")
        op.execute("DROP FUNCTION IF EXISTS update_chat_message_tsv()")
        op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS message_tsv")
        # Drop chat_session tsv trigger if it exists
        op.execute("DROP TRIGGER IF EXISTS chat_session_tsv_trigger ON chat_session")
        op.execute("DROP FUNCTION IF EXISTS update_chat_session_tsv()")
        op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS title_tsv")

        # Drop all indexes that will be created later (using CONCURRENTLY to avoid locking)
        op.execute("COMMIT")  # Required for CONCURRENTLY
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_message_tsv")
        op.execute("COMMIT")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_message_tsv_gen")
        op.execute("COMMIT")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_session_desc_tsv")
        op.execute("COMMIT")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_session_desc_tsv_gen")
        op.execute("COMMIT")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_message_message_lower")
        op.execute("COMMIT")

        # Drop any column on chat_session that will be created
        op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS description_tsv")
        op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS description_tsv_gen")

        # Begin a new transaction before continuing
        op.execute("BEGIN")

        time.time()
        op.execute(
            "ALTER TABLE chat_message ADD COLUMN IF NOT EXISTS message_tsv tsvector"
        )

        # Step 2: Create function and trigger for new/updated rows
        op.execute(
            """
    CREATE OR REPLACE FUNCTION update_chat_message_tsv()
    RETURNS TRIGGER AS $$
    BEGIN
      NEW.message_tsv = to_tsvector('english', NEW.message);
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """
        )

        # Create trigger in a separate execute call
        op.execute(
            """
    CREATE TRIGGER chat_message_tsv_trigger
    BEFORE INSERT OR UPDATE ON chat_message
    FOR EACH ROW EXECUTE FUNCTION update_chat_message_tsv()
    """
        )

        # Step 3: Update existing rows in batches using Python
        time.time()

        # Get connection and count total rows
        connection = op.get_bind()
        total_count_result = connection.execute(
            text("SELECT COUNT(*) FROM chat_message")
        ).scalar()
        total_count = total_count_result if total_count_result is not None else 0
        batch_size = 5000
        batches = 0

        # Calculate total batches needed
        total_batches = (
            (total_count + batch_size - 1) // batch_size if total_count > 0 else 0
        )

        # Process in batches - properly handling UUIDs by using OFFSET/LIMIT approach
        for batch_num in range(total_batches):
            offset = batch_num * batch_size

            # Execute update for this batch using OFFSET/LIMIT which works with UUIDs
            connection.execute(
                text(
                    """
            UPDATE chat_message
            SET message_tsv = to_tsvector('english', message)
            WHERE id IN (
                SELECT id FROM chat_message
                WHERE message_tsv IS NULL
                ORDER BY id
                LIMIT :batch_size OFFSET :offset
            )
            """
                ).bindparams(batch_size=batch_size, offset=offset)
            )

            # Commit each batch
            connection.execute(text("COMMIT"))
            # Start a new transaction
            connection.execute(text("BEGIN"))

            batches += 1

        # Final check for any remaining NULL values
        connection.execute(
            text(
                """
    UPDATE chat_message SET message_tsv = to_tsvector('english', message)
    WHERE message_tsv IS NULL
    """
            )
        )

        # Create GIN index concurrently
        connection.execute(text("COMMIT"))

        time.time()

        connection.execute(
            text(
                """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_message_tsv
    ON chat_message USING GIN (message_tsv)
    """
            )
        )

        # First drop the trigger as it won't be needed anymore
        connection.execute(
            text(
                """
    DROP TRIGGER IF EXISTS chat_message_tsv_trigger ON chat_message;
    """
            )
        )

        connection.execute(
            text(
                """
    DROP FUNCTION IF EXISTS update_chat_message_tsv();
    """
            )
        )

        # Add new generated column
        time.time()
        connection.execute(
            text(
                """
    ALTER TABLE chat_message
    ADD COLUMN message_tsv_gen tsvector
    GENERATED ALWAYS AS (to_tsvector('english', message)) STORED;
    """
            )
        )

        connection.execute(text("COMMIT"))

        time.time()

        connection.execute(
            text(
                """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_message_tsv_gen
    ON chat_message USING GIN (message_tsv_gen)
    """
            )
        )

        # Drop old index and column
        connection.execute(text("COMMIT"))

        connection.execute(
            text(
                """
    DROP INDEX CONCURRENTLY IF EXISTS idx_chat_message_tsv;
    """
            )
        )
        connection.execute(text("COMMIT"))
        connection.execute(
            text(
                """
    ALTER TABLE chat_message DROP COLUMN message_tsv;
    """
            )
        )

        # Rename new column to old name
        connection.execute(
            text(
                """
    ALTER TABLE chat_message RENAME COLUMN message_tsv_gen TO message_tsv;
    """
            )
        )

        # --- PART 2: chat_session table ---

        # Step 1: Add nullable column (quick, minimal locking)
        time.time()
        connection.execute(
            text(
                "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS description_tsv tsvector"
            )
        )

        # Step 2: Create function and trigger for new/updated rows - SPLIT INTO SEPARATE CALLS
        connection.execute(
            text(
                """
    CREATE OR REPLACE FUNCTION update_chat_session_tsv()
    RETURNS TRIGGER AS $$
    BEGIN
      NEW.description_tsv = to_tsvector('english', COALESCE(NEW.description, ''));
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """
            )
        )

        # Create trigger in a separate execute call
        connection.execute(
            text(
                """
    CREATE TRIGGER chat_session_tsv_trigger
    BEFORE INSERT OR UPDATE ON chat_session
    FOR EACH ROW EXECUTE FUNCTION update_chat_session_tsv()
    """
            )
        )

        # Step 3: Update existing rows in batches using Python
        time.time()

        # Get the maximum ID to determine batch count
        # Cast id to text for MAX function since it's a UUID
        max_id_result = connection.execute(
            text("SELECT COALESCE(MAX(id::text), '0') FROM chat_session")
        ).scalar()
        max_id_result if max_id_result is not None else "0"
        batch_size = 5000
        batches = 0

        # Get all IDs ordered to process in batches
        rows = connection.execute(
            text("SELECT id FROM chat_session ORDER BY id")
        ).fetchall()
        total_rows = len(rows)

        # Process in batches
        for batch_num, batch_start in enumerate(range(0, total_rows, batch_size)):
            batch_end = min(batch_start + batch_size, total_rows)
            batch_ids = [row[0] for row in rows[batch_start:batch_end]]

            if not batch_ids:
                continue

            # Use IN clause instead of BETWEEN for UUIDs
            placeholders = ", ".join([f":id{i}" for i in range(len(batch_ids))])
            params = {f"id{i}": id_val for i, id_val in enumerate(batch_ids)}

            # Execute update for this batch
            connection.execute(
                text(
                    f"""
            UPDATE chat_session
            SET description_tsv = to_tsvector('english', COALESCE(description, ''))
            WHERE id IN ({placeholders})
            AND description_tsv IS NULL
            """
                ).bindparams(**params)
            )

            # Commit each batch
            connection.execute(text("COMMIT"))
            # Start a new transaction
            connection.execute(text("BEGIN"))

            batches += 1

        # Final check for any remaining NULL values
        connection.execute(
            text(
                """
    UPDATE chat_session SET description_tsv = to_tsvector('english', COALESCE(description, ''))
    WHERE description_tsv IS NULL
    """
            )
        )

        # Create GIN index concurrently
        connection.execute(text("COMMIT"))

        time.time()
        connection.execute(
            text(
                """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_session_desc_tsv
    ON chat_session USING GIN (description_tsv)
    """
            )
        )

        # After Final check for chat_session
        # First drop the trigger as it won't be needed anymore
        connection.execute(
            text(
                """
    DROP TRIGGER IF EXISTS chat_session_tsv_trigger ON chat_session;
    """
            )
        )

        connection.execute(
            text(
                """
    DROP FUNCTION IF EXISTS update_chat_session_tsv();
    """
            )
        )
        # Add new generated column
        time.time()
        connection.execute(
            text(
                """
    ALTER TABLE chat_session
    ADD COLUMN description_tsv_gen tsvector
    GENERATED ALWAYS AS (to_tsvector('english', COALESCE(description, ''))) STORED;
    """
            )
        )

        # Create new index on generated column
        connection.execute(text("COMMIT"))

        time.time()
        connection.execute(
            text(
                """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_session_desc_tsv_gen
    ON chat_session USING GIN (description_tsv_gen)
    """
            )
        )

        # Drop old index and column
        connection.execute(text("COMMIT"))

        connection.execute(
            text(
                """
    DROP INDEX CONCURRENTLY IF EXISTS idx_chat_session_desc_tsv;
    """
            )
        )
        connection.execute(text("COMMIT"))
        connection.execute(
            text(
                """
    ALTER TABLE chat_session DROP COLUMN description_tsv;
    """
            )
        )

        # Rename new column to old name
        connection.execute(
            text(
                """
    ALTER TABLE chat_session RENAME COLUMN description_tsv_gen TO description_tsv;
    """
            )
        )

    except Exception as e:
        # Make sure to release the lock in case of error
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)").bindparams(
                lock_key=ALEMBIC_MIGRATION_LOCK_KEY
            )
        )
        raise e
    finally:
        # Release the advisory lock when done
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)").bindparams(
                lock_key=ALEMBIC_MIGRATION_LOCK_KEY
            )
        )


def downgrade() -> None:
    # Drop the indexes first (use CONCURRENTLY for dropping too)
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_message_tsv;")

    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chat_session_desc_tsv;")

    # Then drop the columns
    op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS message_tsv;")
    op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS description_tsv;")

    op.execute("DROP INDEX IF EXISTS idx_chat_message_message_lower;")
