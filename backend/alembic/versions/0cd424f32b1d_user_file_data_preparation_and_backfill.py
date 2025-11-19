"""Migration 2: User file data preparation and backfill

Revision ID: 0cd424f32b1d
Revises: 9b66d3156fc6
Create Date: 2025-09-22 09:44:42.727034

This migration populates the new columns added in migration 1.
It prepares data for the UUID transition and relationship migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "0cd424f32b1d"
down_revision = "9b66d3156fc6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Populate new columns with data."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # === Step 1: Populate user_file.new_id ===
    user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]
    has_new_id = "new_id" in user_file_columns

    if has_new_id:
        logger.info("Populating user_file.new_id with UUIDs...")

        # Count rows needing UUIDs
        null_count = bind.execute(
            text("SELECT COUNT(*) FROM user_file WHERE new_id IS NULL")
        ).scalar_one()

        if null_count > 0:
            logger.info(f"Generating UUIDs for {null_count} user_file records...")

            # Populate in batches to avoid long locks
            batch_size = 10000
            total_updated = 0

            while True:
                result = bind.execute(
                    text(
                        """
                    UPDATE user_file
                    SET new_id = gen_random_uuid()
                    WHERE new_id IS NULL
                    AND id IN (
                        SELECT id FROM user_file
                        WHERE new_id IS NULL
                        LIMIT :batch_size
                    )
                """
                    ),
                    {"batch_size": batch_size},
                )

                updated = result.rowcount
                total_updated += updated

                if updated < batch_size:
                    break

                logger.info(f"  Updated {total_updated}/{null_count} records...")

            logger.info(f"Generated UUIDs for {total_updated} user_file records")

        # Verify all records have UUIDs
        remaining_null = bind.execute(
            text("SELECT COUNT(*) FROM user_file WHERE new_id IS NULL")
        ).scalar_one()

        if remaining_null > 0:
            raise Exception(
                f"Failed to populate all user_file.new_id values ({remaining_null} NULL)"
            )

        # Lock down the column
        op.alter_column("user_file", "new_id", nullable=False)
        op.alter_column("user_file", "new_id", server_default=None)
        logger.info("Locked down user_file.new_id column")

    # === Step 2: Populate persona__user_file.user_file_id_uuid ===
    persona_user_file_columns = [
        col["name"] for col in inspector.get_columns("persona__user_file")
    ]

    if has_new_id and "user_file_id_uuid" in persona_user_file_columns:
        logger.info("Populating persona__user_file.user_file_id_uuid...")

        # Count rows needing update
        null_count = bind.execute(
            text(
                """
            SELECT COUNT(*) FROM persona__user_file
            WHERE user_file_id IS NOT NULL AND user_file_id_uuid IS NULL
        """
            )
        ).scalar_one()

        if null_count > 0:
            logger.info(f"Updating {null_count} persona__user_file records...")

            # Update in batches
            batch_size = 10000
            total_updated = 0

            while True:
                result = bind.execute(
                    text(
                        """
                    UPDATE persona__user_file p
                    SET user_file_id_uuid = uf.new_id
                    FROM user_file uf
                    WHERE p.user_file_id = uf.id
                    AND p.user_file_id_uuid IS NULL
                    AND p.persona_id IN (
                        SELECT persona_id
                        FROM persona__user_file
                        WHERE user_file_id_uuid IS NULL
                        LIMIT :batch_size
                    )
                """
                    ),
                    {"batch_size": batch_size},
                )

                updated = result.rowcount
                total_updated += updated

                if updated < batch_size:
                    break

                logger.info(f"  Updated {total_updated}/{null_count} records...")

            logger.info(f"Updated {total_updated} persona__user_file records")

        # Verify all records are populated
        remaining_null = bind.execute(
            text(
                """
            SELECT COUNT(*) FROM persona__user_file
            WHERE user_file_id IS NOT NULL AND user_file_id_uuid IS NULL
        """
            )
        ).scalar_one()

        if remaining_null > 0:
            raise Exception(
                f"Failed to populate all persona__user_file.user_file_id_uuid values ({remaining_null} NULL)"
            )

        op.alter_column("persona__user_file", "user_file_id_uuid", nullable=False)
        logger.info("Locked down persona__user_file.user_file_id_uuid column")

    # === Step 3: Create user_project records from chat_folder ===
    if "chat_folder" in inspector.get_table_names():
        logger.info("Creating user_project records from chat_folder...")

        result = bind.execute(
            text(
                """
            INSERT INTO user_project (user_id, name)
            SELECT cf.user_id, cf.name
            FROM chat_folder cf
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_project up
                WHERE up.user_id = cf.user_id AND up.name = cf.name
            )
        """
            )
        )

        logger.info(f"Created {result.rowcount} user_project records from chat_folder")

    # === Step 4: Populate chat_session.project_id ===
    chat_session_columns = [
        col["name"] for col in inspector.get_columns("chat_session")
    ]

    if "folder_id" in chat_session_columns and "project_id" in chat_session_columns:
        logger.info("Populating chat_session.project_id...")

        # Count sessions needing update
        null_count = bind.execute(
            text(
                """
            SELECT COUNT(*) FROM chat_session
            WHERE project_id IS NULL AND folder_id IS NOT NULL
        """
            )
        ).scalar_one()

        if null_count > 0:
            logger.info(f"Updating {null_count} chat_session records...")

            result = bind.execute(
                text(
                    """
                UPDATE chat_session cs
                SET project_id = up.id
                FROM chat_folder cf
                JOIN user_project up ON up.user_id = cf.user_id AND up.name = cf.name
                WHERE cs.folder_id = cf.id AND cs.project_id IS NULL
            """
                )
            )

            logger.info(f"Updated {result.rowcount} chat_session records")

        # Verify all records are populated
        remaining_null = bind.execute(
            text(
                """
            SELECT COUNT(*) FROM chat_session
            WHERE project_id IS NULL AND folder_id IS NOT NULL
        """
            )
        ).scalar_one()

        if remaining_null > 0:
            logger.warning(
                f"Warning: {remaining_null} chat_session records could not be mapped to projects"
            )

    # === Step 5: Update plaintext FileRecord IDs/display names to UUID scheme ===
    # Prior to UUID migration, plaintext cache files were stored with file_id like 'plain_text_<int_id>'.
    # After migration, we use 'plaintext_<uuid>' (note the name change to 'plaintext_').
    # This step remaps existing FileRecord rows to the new naming while preserving object_key/bucket.
    logger.info("Updating plaintext FileRecord ids and display names to UUID scheme...")

    # Count legacy plaintext records that can be mapped to UUID user_file ids
    count_query = text(
        """
        SELECT COUNT(*)
        FROM file_record fr
        JOIN user_file uf ON fr.file_id = CONCAT('plaintext_', uf.id::text)
        WHERE LOWER(fr.file_origin::text) = 'plaintext_cache'
        """
    )
    legacy_count = bind.execute(count_query).scalar_one()

    if legacy_count and legacy_count > 0:
        logger.info(f"Found {legacy_count} legacy plaintext file records to update")

        # Update display_name first for readability (safe regardless of rename)
        bind.execute(
            text(
                """
                UPDATE file_record fr
                SET display_name = CONCAT('Plaintext for user file ', uf.new_id::text)
                FROM user_file uf
                WHERE LOWER(fr.file_origin::text) = 'plaintext_cache'
                    AND fr.file_id = CONCAT('plaintext_', uf.id::text)
                """
            )
        )

        # Remap file_id from 'plaintext_<int>' -> 'plaintext_<uuid>' using transitional new_id
        # Use a single UPDATE ... WHERE file_id LIKE 'plain_text_%'
        # and ensure it aligns to existing user_file ids to avoid renaming unrelated rows
        result = bind.execute(
            text(
                """
                UPDATE file_record fr
                SET file_id = CONCAT('plaintext_', uf.new_id::text)
                FROM user_file uf
                WHERE LOWER(fr.file_origin::text) = 'plaintext_cache'
                    AND fr.file_id = CONCAT('plaintext_', uf.id::text)
                """
            )
        )
        logger.info(
            f"Updated {result.rowcount} plaintext file_record ids to UUID scheme"
        )

    # === Step 6: Ensure document_id_migrated default TRUE and backfill existing FALSE ===
    # New records should default to migrated=True so the migration task won't run for them.
    # Existing rows that had a legacy document_id should be marked as not migrated to be processed.

    # Backfill existing records: if document_id is not null, set to FALSE
    bind.execute(
        text(
            """
            UPDATE user_file
            SET document_id_migrated = FALSE
            WHERE document_id IS NOT NULL
            """
        )
    )

    # === Step 7: Backfill user_file.status from index_attempt ===
    logger.info("Backfilling user_file.status from index_attempt...")

    # Update user_file status based on latest index attempt
    # Using CTEs instead of temp tables for asyncpg compatibility
    result = bind.execute(
        text(
            """
        WITH latest_attempt AS (
            SELECT DISTINCT ON (ia.connector_credential_pair_id)
                ia.connector_credential_pair_id,
                ia.status
            FROM index_attempt ia
            ORDER BY ia.connector_credential_pair_id, ia.time_updated DESC
        ),
        uf_to_ccp AS (
            SELECT DISTINCT uf.id AS uf_id, ccp.id AS cc_pair_id
            FROM user_file uf
            JOIN document_by_connector_credential_pair dcc
                ON dcc.id = REPLACE(uf.document_id, 'USER_FILE_CONNECTOR__', 'FILE_CONNECTOR__')
            JOIN connector_credential_pair ccp
                ON ccp.connector_id = dcc.connector_id
                AND ccp.credential_id = dcc.credential_id
        )
        UPDATE user_file uf
        SET status = CASE
            WHEN la.status IN ('NOT_STARTED', 'IN_PROGRESS') THEN 'PROCESSING'
            WHEN la.status = 'SUCCESS' THEN 'COMPLETED'
            ELSE 'FAILED'
        END
        FROM uf_to_ccp ufc
        LEFT JOIN latest_attempt la
            ON la.connector_credential_pair_id = ufc.cc_pair_id
        WHERE uf.id = ufc.uf_id
        AND uf.status = 'PROCESSING'
    """
        )
    )

    logger.info(f"Updated status for {result.rowcount} user_file records")

    logger.info("Migration 2 (data preparation) completed successfully")


def downgrade() -> None:
    """Reset populated data to allow clean downgrade of schema."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.info("Starting downgrade of data preparation...")

    # Reset user_file columns to allow nulls before data removal
    if "user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_file")]

        if "new_id" in columns:
            op.alter_column(
                "user_file",
                "new_id",
                nullable=True,
                server_default=sa.text("gen_random_uuid()"),
            )
            # Optionally clear the data
            # bind.execute(text("UPDATE user_file SET new_id = NULL"))
            logger.info("Reset user_file.new_id to nullable")

    # Reset persona__user_file.user_file_id_uuid
    if "persona__user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("persona__user_file")]

        if "user_file_id_uuid" in columns:
            op.alter_column("persona__user_file", "user_file_id_uuid", nullable=True)
            # Optionally clear the data
            # bind.execute(text("UPDATE persona__user_file SET user_file_id_uuid = NULL"))
            logger.info("Reset persona__user_file.user_file_id_uuid to nullable")

    # Note: We don't delete user_project records or reset chat_session.project_id
    # as these might be in use and can be handled by the schema downgrade

    # Reset user_file.status to default
    if "user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_file")]
        if "status" in columns:
            bind.execute(text("UPDATE user_file SET status = 'PROCESSING'"))
            logger.info("Reset user_file.status to default")

    logger.info("Downgrade completed successfully")
