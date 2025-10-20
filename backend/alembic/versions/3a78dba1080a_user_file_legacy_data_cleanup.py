"""Migration 5: User file legacy data cleanup

Revision ID: 3a78dba1080a
Revises: 7cc3fcc116c1
Create Date: 2025-09-22 10:04:27.986294

This migration removes legacy user-file documents and connector_credential_pairs.
It performs bulk deletions of obsolete data after the UUID migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql
from sqlalchemy import text
import logging
from typing import List
import uuid

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "3a78dba1080a"
down_revision = "7cc3fcc116c1"
branch_labels = None
depends_on = None


def batch_delete(
    bind: sa.engine.Connection,
    table_name: str,
    id_column: str,
    ids: List[str | int | uuid.UUID],
    batch_size: int = 1000,
    id_type: str = "int",
) -> int:
    """Delete records in batches to avoid memory issues and timeouts."""
    total_count = len(ids)
    if total_count == 0:
        return 0

    logger.info(
        f"Starting batch deletion of {total_count} records from {table_name}..."
    )

    # Determine appropriate ARRAY type
    if id_type == "uuid":
        array_type = psql.ARRAY(psql.UUID(as_uuid=True))
    elif id_type == "int":
        array_type = psql.ARRAY(sa.Integer())
    else:
        array_type = psql.ARRAY(sa.String())

    total_deleted = 0
    failed_batches = []

    for i in range(0, total_count, batch_size):
        batch_ids = ids[i : i + batch_size]
        try:
            stmt = text(
                f"DELETE FROM {table_name} WHERE {id_column} = ANY(:ids)"
            ).bindparams(sa.bindparam("ids", value=batch_ids, type_=array_type))
            result = bind.execute(stmt)
            total_deleted += result.rowcount

            # Log progress every 10 batches or at completion
            batch_num = (i // batch_size) + 1
            if batch_num % 10 == 0 or i + batch_size >= total_count:
                logger.info(
                    f"  Deleted {min(i + batch_size, total_count)}/{total_count} records "
                    f"({total_deleted} actual) from {table_name}"
                )
        except Exception as e:
            logger.error(f"Failed to delete batch {(i // batch_size) + 1}: {e}")
            failed_batches.append((i, min(i + batch_size, total_count)))

    if failed_batches:
        logger.warning(
            f"Failed to delete {len(failed_batches)} batches from {table_name}. "
            f"Total deleted: {total_deleted}/{total_count}"
        )
        # Fail the migration to avoid silently succeeding on partial cleanup
        raise RuntimeError(
            f"Batch deletion failed for {table_name}: "
            f"{len(failed_batches)} failed batches out of "
            f"{(total_count + batch_size - 1) // batch_size}."
        )

    return total_deleted


def upgrade() -> None:
    """Remove legacy user-file documents and connector_credential_pairs."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.info("Starting legacy data cleanup...")

    # === Step 1: Identify and delete user-file documents ===
    logger.info("Identifying user-file documents to delete...")

    # Get document IDs to delete
    doc_rows = bind.execute(
        text(
            """
        SELECT DISTINCT dcc.id AS document_id
        FROM document_by_connector_credential_pair dcc
        JOIN connector_credential_pair u
          ON u.connector_id = dcc.connector_id
         AND u.credential_id = dcc.credential_id
        WHERE u.is_user_file IS TRUE
    """
        )
    ).fetchall()

    doc_ids = [r[0] for r in doc_rows]

    if doc_ids:
        logger.info(f"Found {len(doc_ids)} user-file documents to delete")

        # Delete dependent rows first
        tables_to_clean = [
            ("document_retrieval_feedback", "document_id"),
            ("document__tag", "document_id"),
            ("chunk_stats", "document_id"),
        ]

        for table_name, column_name in tables_to_clean:
            if table_name in inspector.get_table_names():
                # document_id is a string in these tables
                deleted = batch_delete(
                    bind, table_name, column_name, doc_ids, id_type="str"
                )
                logger.info(f"Deleted {deleted} records from {table_name}")

        # Delete document_by_connector_credential_pair entries
        deleted = batch_delete(
            bind, "document_by_connector_credential_pair", "id", doc_ids, id_type="str"
        )
        logger.info(f"Deleted {deleted} document_by_connector_credential_pair records")

        # Delete documents themselves
        deleted = batch_delete(bind, "document", "id", doc_ids, id_type="str")
        logger.info(f"Deleted {deleted} document records")
    else:
        logger.info("No user-file documents found to delete")

    # === Step 2: Clean up user-file connector_credential_pairs ===
    logger.info("Cleaning up user-file connector_credential_pairs...")

    # Get cc_pair IDs
    cc_pair_rows = bind.execute(
        text(
            """
        SELECT id AS cc_pair_id
        FROM connector_credential_pair
        WHERE is_user_file IS TRUE
    """
        )
    ).fetchall()

    cc_pair_ids = [r[0] for r in cc_pair_rows]

    if cc_pair_ids:
        logger.info(
            f"Found {len(cc_pair_ids)} user-file connector_credential_pairs to clean up"
        )

        # Delete related records
        # Clean child tables first to satisfy foreign key constraints,
        # then the parent tables
        tables_to_clean = [
            ("index_attempt_errors", "connector_credential_pair_id"),
            ("index_attempt", "connector_credential_pair_id"),
            ("background_error", "cc_pair_id"),
            ("document_set__connector_credential_pair", "connector_credential_pair_id"),
            ("user_group__connector_credential_pair", "cc_pair_id"),
        ]

        for table_name, column_name in tables_to_clean:
            if table_name in inspector.get_table_names():
                deleted = batch_delete(
                    bind, table_name, column_name, cc_pair_ids, id_type="int"
                )
                logger.info(f"Deleted {deleted} records from {table_name}")

    # === Step 3: Identify connectors and credentials to delete ===
    logger.info("Identifying orphaned connectors and credentials...")

    # Get connectors used only by user-file cc_pairs
    connector_rows = bind.execute(
        text(
            """
        SELECT DISTINCT ccp.connector_id
        FROM connector_credential_pair ccp
        WHERE ccp.is_user_file IS TRUE
          AND ccp.connector_id != 0  -- Exclude system default
          AND NOT EXISTS (
            SELECT 1
            FROM connector_credential_pair c2
            WHERE c2.connector_id = ccp.connector_id
              AND c2.is_user_file IS NOT TRUE
          )
    """
        )
    ).fetchall()

    userfile_only_connector_ids = [r[0] for r in connector_rows]

    # Get credentials used only by user-file cc_pairs
    credential_rows = bind.execute(
        text(
            """
        SELECT DISTINCT ccp.credential_id
        FROM connector_credential_pair ccp
        WHERE ccp.is_user_file IS TRUE
          AND ccp.credential_id != 0  -- Exclude public/default
          AND NOT EXISTS (
            SELECT 1
            FROM connector_credential_pair c2
            WHERE c2.credential_id = ccp.credential_id
              AND c2.is_user_file IS NOT TRUE
          )
    """
        )
    ).fetchall()

    userfile_only_credential_ids = [r[0] for r in credential_rows]

    # === Step 4: Delete the cc_pairs themselves ===
    if cc_pair_ids:
        # Remove FK dependency from user_file first
        bind.execute(
            text(
                """
            DO $$
            DECLARE r RECORD;
            BEGIN
              FOR r IN (
                SELECT conname
                FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                JOIN pg_class ft ON c.confrelid = ft.oid
                WHERE c.contype = 'f'
                  AND t.relname = 'user_file'
                  AND ft.relname = 'connector_credential_pair'
              ) LOOP
                EXECUTE format('ALTER TABLE user_file DROP CONSTRAINT IF EXISTS %I', r.conname);
              END LOOP;
            END$$;
        """
            )
        )

        # Delete cc_pairs
        deleted = batch_delete(
            bind, "connector_credential_pair", "id", cc_pair_ids, id_type="int"
        )
        logger.info(f"Deleted {deleted} connector_credential_pair records")

    # === Step 5: Delete orphaned connectors ===
    if userfile_only_connector_ids:
        deleted = batch_delete(
            bind, "connector", "id", userfile_only_connector_ids, id_type="int"
        )
        logger.info(f"Deleted {deleted} orphaned connector records")

    # === Step 6: Delete orphaned credentials ===
    if userfile_only_credential_ids:
        # Clean up credential__user_group mappings first
        deleted = batch_delete(
            bind,
            "credential__user_group",
            "credential_id",
            userfile_only_credential_ids,
            id_type="int",
        )
        logger.info(f"Deleted {deleted} credential__user_group records")

        # Delete credentials
        deleted = batch_delete(
            bind, "credential", "id", userfile_only_credential_ids, id_type="int"
        )
        logger.info(f"Deleted {deleted} orphaned credential records")

    logger.info("Migration 5 (legacy data cleanup) completed successfully")


def downgrade() -> None:
    """Cannot restore deleted data - requires backup restoration."""

    logger.error("CRITICAL: Downgrading data cleanup cannot restore deleted data!")
    logger.error("Data restoration requires backup files or database backup.")

    raise NotImplementedError(
        "Downgrade of legacy data cleanup is not supported. "
        "Deleted data must be restored from backups."
    )
