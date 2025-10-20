"""Migration 1: User file schema additions

Revision ID: 9b66d3156fc6
Revises: b4ef3ae0bf6e
Create Date: 2025-09-22 09:42:06.086732

This migration adds new columns and tables without modifying existing data.
It is safe to run and can be easily rolled back.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql
import logging

logger = logging.getLogger("alembic.runtime.migration")
# revision identifiers, used by Alembic.
revision = "9b66d3156fc6"
down_revision = "b4ef3ae0bf6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add new columns and tables without modifying existing data."""

    # Enable pgcrypto for UUID generation
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # === USER_FILE: Add new columns ===
    logger.info("Adding new columns to user_file table...")

    user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]

    # Check if ID is already UUID (in case of re-run after partial migration)
    id_is_uuid = any(
        col["name"] == "id" and "uuid" in str(col["type"]).lower()
        for col in inspector.get_columns("user_file")
    )

    # Add transitional UUID column only if ID is not already UUID
    if "new_id" not in user_file_columns and not id_is_uuid:
        op.add_column(
            "user_file",
            sa.Column(
                "new_id",
                psql.UUID(as_uuid=True),
                nullable=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
        )
        op.create_unique_constraint("uq_user_file_new_id", "user_file", ["new_id"])
        logger.info("Added new_id column to user_file")

    # Add status column
    if "status" not in user_file_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "status",
                sa.Enum(
                    "PROCESSING",
                    "COMPLETED",
                    "FAILED",
                    "CANCELED",
                    name="userfilestatus",
                    native_enum=False,
                ),
                nullable=False,
                server_default="PROCESSING",
            ),
        )
        logger.info("Added status column to user_file")

    # Add other tracking columns
    if "chunk_count" not in user_file_columns:
        op.add_column(
            "user_file", sa.Column("chunk_count", sa.Integer(), nullable=True)
        )
        logger.info("Added chunk_count column to user_file")

    if "last_accessed_at" not in user_file_columns:
        op.add_column(
            "user_file",
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        )
        logger.info("Added last_accessed_at column to user_file")

    if "needs_project_sync" not in user_file_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "needs_project_sync",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        logger.info("Added needs_project_sync column to user_file")

    if "last_project_sync_at" not in user_file_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "last_project_sync_at", sa.DateTime(timezone=True), nullable=True
            ),
        )
        logger.info("Added last_project_sync_at column to user_file")

    if "document_id_migrated" not in user_file_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "document_id_migrated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        logger.info("Added document_id_migrated column to user_file")

    # === USER_FOLDER -> USER_PROJECT rename ===
    table_names = set(inspector.get_table_names())

    if "user_folder" in table_names:
        logger.info("Updating user_folder table...")
        # Make description nullable first
        op.alter_column("user_folder", "description", nullable=True)

        # Rename table if user_project doesn't exist
        if "user_project" not in table_names:
            op.execute("ALTER TABLE user_folder RENAME TO user_project")
            logger.info("Renamed user_folder to user_project")
    elif "user_project" in table_names:
        # If already renamed, ensure column nullability
        project_cols = [col["name"] for col in inspector.get_columns("user_project")]
        if "description" in project_cols:
            op.alter_column("user_project", "description", nullable=True)

    # Add instructions column to user_project
    inspector = sa.inspect(bind)  # Refresh after rename
    if "user_project" in inspector.get_table_names():
        project_columns = [col["name"] for col in inspector.get_columns("user_project")]
        if "instructions" not in project_columns:
            op.add_column(
                "user_project",
                sa.Column("instructions", sa.String(), nullable=True),
            )
            logger.info("Added instructions column to user_project")

    # === CHAT_SESSION: Add project_id ===
    chat_session_columns = [
        col["name"] for col in inspector.get_columns("chat_session")
    ]
    if "project_id" not in chat_session_columns:
        op.add_column(
            "chat_session",
            sa.Column("project_id", sa.Integer(), nullable=True),
        )
        logger.info("Added project_id column to chat_session")

    # === PERSONA__USER_FILE: Add UUID column ===
    persona_user_file_columns = [
        col["name"] for col in inspector.get_columns("persona__user_file")
    ]
    if "user_file_id_uuid" not in persona_user_file_columns:
        op.add_column(
            "persona__user_file",
            sa.Column("user_file_id_uuid", psql.UUID(as_uuid=True), nullable=True),
        )
        logger.info("Added user_file_id_uuid column to persona__user_file")

    # === PROJECT__USER_FILE: Create new table ===
    if "project__user_file" not in inspector.get_table_names():
        op.create_table(
            "project__user_file",
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("user_file_id", psql.UUID(as_uuid=True), nullable=False),
            sa.PrimaryKeyConstraint("project_id", "user_file_id"),
        )
        op.create_index(
            "idx_project__user_file_user_file_id",
            "project__user_file",
            ["user_file_id"],
        )
        logger.info("Created project__user_file table")

    logger.info("Migration 1 (schema additions) completed successfully")


def downgrade() -> None:
    """Remove added columns and tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    logger.info("Starting downgrade of schema additions...")

    # Drop project__user_file table
    if "project__user_file" in inspector.get_table_names():
        op.drop_index("idx_project__user_file_user_file_id", "project__user_file")
        op.drop_table("project__user_file")
        logger.info("Dropped project__user_file table")

    # Remove columns from persona__user_file
    if "persona__user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("persona__user_file")]
        if "user_file_id_uuid" in columns:
            op.drop_column("persona__user_file", "user_file_id_uuid")
            logger.info("Dropped user_file_id_uuid from persona__user_file")

    # Remove columns from chat_session
    if "chat_session" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("chat_session")]
        if "project_id" in columns:
            op.drop_column("chat_session", "project_id")
            logger.info("Dropped project_id from chat_session")

    # Rename user_project back to user_folder and remove instructions
    if "user_project" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_project")]
        if "instructions" in columns:
            op.drop_column("user_project", "instructions")
        op.execute("ALTER TABLE user_project RENAME TO user_folder")
        op.alter_column("user_folder", "description", nullable=False)
        logger.info("Renamed user_project back to user_folder")

    # Remove columns from user_file
    if "user_file" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_file")]

        columns_to_drop = [
            "document_id_migrated",
            "last_project_sync_at",
            "needs_project_sync",
            "last_accessed_at",
            "chunk_count",
            "status",
        ]

        for col in columns_to_drop:
            if col in columns:
                op.drop_column("user_file", col)
                logger.info(f"Dropped {col} from user_file")

        if "new_id" in columns:
            op.drop_constraint("uq_user_file_new_id", "user_file", type_="unique")
            op.drop_column("user_file", "new_id")
            logger.info("Dropped new_id from user_file")

    # Drop enum type if no columns use it
    bind.execute(sa.text("DROP TYPE IF EXISTS userfilestatus"))

    logger.info("Downgrade completed successfully")
