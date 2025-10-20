"""Migration 3: User file relationship migration

Revision ID: 16c37a30adf2
Revises: 0cd424f32b1d
Create Date: 2025-09-22 09:47:34.175596

This migration converts folder-based relationships to project-based relationships.
It migrates persona__user_folder to persona__user_file and populates project__user_file.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "16c37a30adf2"
down_revision = "0cd424f32b1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate folder-based relationships to project-based relationships."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # === Step 1: Migrate persona__user_folder to persona__user_file ===
    table_names = inspector.get_table_names()

    if "persona__user_folder" in table_names and "user_file" in table_names:
        user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]
        has_new_id = "new_id" in user_file_columns

        if has_new_id and "folder_id" in user_file_columns:
            logger.info(
                "Migrating persona__user_folder relationships to persona__user_file..."
            )

            # Count relationships to migrate (asyncpg-compatible)
            count_query = text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT puf.persona_id, uf.id
                    FROM persona__user_folder puf
                    JOIN user_file uf ON uf.folder_id = puf.user_folder_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM persona__user_file p2
                        WHERE p2.persona_id = puf.persona_id
                        AND p2.user_file_id = uf.id
                    )
                ) AS distinct_pairs
            """
            )
            to_migrate = bind.execute(count_query).scalar_one()

            if to_migrate > 0:
                logger.info(f"Creating {to_migrate} persona-file relationships...")

                # Migrate in batches to avoid memory issues
                batch_size = 10000
                total_inserted = 0

                while True:
                    # Insert batch directly using subquery (asyncpg compatible)
                    result = bind.execute(
                        text(
                            """
                        INSERT INTO persona__user_file (persona_id, user_file_id, user_file_id_uuid)
                        SELECT DISTINCT puf.persona_id, uf.id as file_id, uf.new_id
                        FROM persona__user_folder puf
                        JOIN user_file uf ON uf.folder_id = puf.user_folder_id
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM persona__user_file p2
                            WHERE p2.persona_id = puf.persona_id
                            AND p2.user_file_id = uf.id
                        )
                        LIMIT :batch_size
                    """
                        ),
                        {"batch_size": batch_size},
                    )

                    inserted = result.rowcount
                    total_inserted += inserted

                    if inserted < batch_size:
                        break

                    logger.info(
                        f"  Migrated {total_inserted}/{to_migrate} relationships..."
                    )

                logger.info(
                    f"Created {total_inserted} persona__user_file relationships"
                )

    # === Step 2: Add foreign key for chat_session.project_id ===
    chat_session_fks = inspector.get_foreign_keys("chat_session")
    fk_exists = any(
        fk["name"] == "fk_chat_session_project_id" for fk in chat_session_fks
    )

    if not fk_exists:
        logger.info("Adding foreign key constraint for chat_session.project_id...")
        op.create_foreign_key(
            "fk_chat_session_project_id",
            "chat_session",
            "user_project",
            ["project_id"],
            ["id"],
        )
        logger.info("Added foreign key constraint")

    # === Step 3: Populate project__user_file from user_file.folder_id ===
    user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]
    has_new_id = "new_id" in user_file_columns

    if has_new_id and "folder_id" in user_file_columns:
        logger.info("Populating project__user_file from folder relationships...")

        # Count relationships to create
        count_query = text(
            """
            SELECT COUNT(*)
            FROM user_file uf
            WHERE uf.folder_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM project__user_file puf
                WHERE puf.project_id = uf.folder_id
                AND puf.user_file_id = uf.new_id
            )
        """
        )
        to_create = bind.execute(count_query).scalar_one()

        if to_create > 0:
            logger.info(f"Creating {to_create} project-file relationships...")

            # Insert in batches
            batch_size = 10000
            total_inserted = 0

            while True:
                result = bind.execute(
                    text(
                        """
                    INSERT INTO project__user_file (project_id, user_file_id)
                    SELECT uf.folder_id, uf.new_id
                    FROM user_file uf
                    WHERE uf.folder_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM project__user_file puf
                        WHERE puf.project_id = uf.folder_id
                        AND puf.user_file_id = uf.new_id
                    )
                    LIMIT :batch_size
                    ON CONFLICT (project_id, user_file_id) DO NOTHING
                """
                    ),
                    {"batch_size": batch_size},
                )

                inserted = result.rowcount
                total_inserted += inserted

                if inserted < batch_size:
                    break

                logger.info(f"  Created {total_inserted}/{to_create} relationships...")

            logger.info(f"Created {total_inserted} project__user_file relationships")

    # === Step 4: Create index on chat_session.project_id ===
    try:
        indexes = [ix.get("name") for ix in inspector.get_indexes("chat_session")]
    except Exception:
        indexes = []

    if "ix_chat_session_project_id" not in indexes:
        logger.info("Creating index on chat_session.project_id...")
        op.create_index(
            "ix_chat_session_project_id", "chat_session", ["project_id"], unique=False
        )
        logger.info("Created index")

    logger.info("Migration 3 (relationship migration) completed successfully")


def downgrade() -> None:
    """Remove migrated relationships and constraints."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.info("Starting downgrade of relationship migration...")

    # Drop index on chat_session.project_id
    try:
        indexes = [ix.get("name") for ix in inspector.get_indexes("chat_session")]
        if "ix_chat_session_project_id" in indexes:
            op.drop_index("ix_chat_session_project_id", "chat_session")
            logger.info("Dropped index on chat_session.project_id")
    except Exception:
        pass

    # Drop foreign key constraint
    try:
        chat_session_fks = inspector.get_foreign_keys("chat_session")
        fk_exists = any(
            fk["name"] == "fk_chat_session_project_id" for fk in chat_session_fks
        )
        if fk_exists:
            op.drop_constraint(
                "fk_chat_session_project_id", "chat_session", type_="foreignkey"
            )
            logger.info("Dropped foreign key constraint on chat_session.project_id")
    except Exception:
        pass

    # Clear project__user_file relationships (but keep the table for migration 1 to handle)
    if "project__user_file" in inspector.get_table_names():
        result = bind.execute(text("DELETE FROM project__user_file"))
        logger.info(f"Cleared {result.rowcount} records from project__user_file")

    # Remove migrated persona__user_file relationships
    # Only remove those that came from folder relationships
    if all(
        table in inspector.get_table_names()
        for table in ["persona__user_file", "persona__user_folder", "user_file"]
    ):
        user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]
        if "folder_id" in user_file_columns:
            result = bind.execute(
                text(
                    """
                DELETE FROM persona__user_file puf
                WHERE EXISTS (
                    SELECT 1
                    FROM user_file uf
                    JOIN persona__user_folder puf2
                        ON puf2.user_folder_id = uf.folder_id
                    WHERE puf.persona_id = puf2.persona_id
                    AND puf.user_file_id = uf.id
                )
            """
                )
            )
            logger.info(
                f"Removed {result.rowcount} migrated persona__user_file relationships"
            )

    logger.info("Downgrade completed successfully")
