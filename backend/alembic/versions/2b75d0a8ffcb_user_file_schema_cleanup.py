"""Migration 6: User file schema cleanup

Revision ID: 2b75d0a8ffcb
Revises: 3a78dba1080a
Create Date: 2025-09-22 10:09:26.375377

This migration removes legacy columns and tables after data migration is complete.
It should only be run after verifying all data has been successfully migrated.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "2b75d0a8ffcb"
down_revision = "3a78dba1080a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove legacy columns and tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.info("Starting schema cleanup...")

    # === Step 1: Verify data migration is complete ===
    logger.info("Verifying data migration completion...")

    # Check if any chat sessions still have folder_id references
    chat_session_columns = [
        col["name"] for col in inspector.get_columns("chat_session")
    ]
    if "folder_id" in chat_session_columns:
        orphaned_count = bind.execute(
            text(
                """
            SELECT COUNT(*) FROM chat_session
            WHERE folder_id IS NOT NULL AND project_id IS NULL
        """
            )
        ).scalar_one()

        if orphaned_count > 0:
            logger.warning(
                f"WARNING: {orphaned_count} chat_session records still have "
                f"folder_id without project_id. Proceeding anyway."
            )

    # === Step 2: Drop chat_session.folder_id ===
    if "folder_id" in chat_session_columns:
        logger.info("Dropping chat_session.folder_id...")

        # Drop foreign key constraint first
        op.execute(
            "ALTER TABLE chat_session DROP CONSTRAINT IF EXISTS chat_session_folder_fk"
        )

        # Drop the column
        op.drop_column("chat_session", "folder_id")
        logger.info("Dropped chat_session.folder_id")

    # === Step 3: Drop persona__user_folder table ===
    if "persona__user_folder" in inspector.get_table_names():
        logger.info("Dropping persona__user_folder table...")

        # Check for any remaining data
        remaining = bind.execute(
            text("SELECT COUNT(*) FROM persona__user_folder")
        ).scalar_one()

        if remaining > 0:
            logger.warning(
                f"WARNING: Dropping persona__user_folder with {remaining} records"
            )

        op.drop_table("persona__user_folder")
        logger.info("Dropped persona__user_folder table")

    # === Step 4: Drop chat_folder table ===
    if "chat_folder" in inspector.get_table_names():
        logger.info("Dropping chat_folder table...")

        # Check for any remaining data
        remaining = bind.execute(text("SELECT COUNT(*) FROM chat_folder")).scalar_one()

        if remaining > 0:
            logger.warning(f"WARNING: Dropping chat_folder with {remaining} records")

        op.drop_table("chat_folder")
        logger.info("Dropped chat_folder table")

    # === Step 5: Drop user_file legacy columns ===
    user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]

    # Drop folder_id
    if "folder_id" in user_file_columns:
        logger.info("Dropping user_file.folder_id...")
        op.drop_column("user_file", "folder_id")
        logger.info("Dropped user_file.folder_id")

    # Drop cc_pair_id (already handled in migration 5, but be sure)
    if "cc_pair_id" in user_file_columns:
        logger.info("Dropping user_file.cc_pair_id...")

        # Drop any remaining foreign key constraints
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
                WHERE c.contype = 'f'
                  AND t.relname = 'user_file'
                  AND EXISTS (
                    SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = t.oid
                    AND a.attname = 'cc_pair_id'
                  )
              ) LOOP
                EXECUTE format('ALTER TABLE user_file DROP CONSTRAINT IF EXISTS %I', r.conname);
              END LOOP;
            END$$;
        """
            )
        )

        op.drop_column("user_file", "cc_pair_id")
        logger.info("Dropped user_file.cc_pair_id")

    # === Step 6: Clean up any remaining constraints ===
    logger.info("Cleaning up remaining constraints...")

    # Drop any unique constraints on removed columns
    op.execute(
        "ALTER TABLE user_file DROP CONSTRAINT IF EXISTS user_file_cc_pair_id_key"
    )

    logger.info("Migration 6 (schema cleanup) completed successfully")
    logger.info("Legacy schema has been fully removed")


def downgrade() -> None:
    """Recreate dropped columns and tables (structure only, no data)."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.warning("Downgrading schema cleanup - recreating structure only, no data!")

    # Recreate user_file columns
    if "user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_file")]

        if "cc_pair_id" not in columns:
            op.add_column(
                "user_file", sa.Column("cc_pair_id", sa.Integer(), nullable=True)
            )

        if "folder_id" not in columns:
            op.add_column(
                "user_file", sa.Column("folder_id", sa.Integer(), nullable=True)
            )

    # Recreate chat_folder table
    if "chat_folder" not in inspector.get_table_names():
        op.create_table(
            "chat_folder",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["user.id"], name="chat_folder_user_fk"
            ),
        )

    # Recreate persona__user_folder table
    if "persona__user_folder" not in inspector.get_table_names():
        op.create_table(
            "persona__user_folder",
            sa.Column("persona_id", sa.Integer(), nullable=False),
            sa.Column("user_folder_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("persona_id", "user_folder_id"),
            sa.ForeignKeyConstraint(["persona_id"], ["persona.id"]),
            sa.ForeignKeyConstraint(["user_folder_id"], ["user_project.id"]),
        )

    # Add folder_id back to chat_session
    if "chat_session" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("chat_session")]
        if "folder_id" not in columns:
            op.add_column(
                "chat_session", sa.Column("folder_id", sa.Integer(), nullable=True)
            )

            # Add foreign key if chat_folder exists
            if "chat_folder" in inspector.get_table_names():
                op.create_foreign_key(
                    "chat_session_folder_fk",
                    "chat_session",
                    "chat_folder",
                    ["folder_id"],
                    ["id"],
                )

    logger.info("Downgrade completed - structure recreated but data is lost")
