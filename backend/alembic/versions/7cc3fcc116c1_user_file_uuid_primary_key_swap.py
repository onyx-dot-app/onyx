"""Migration 4: User file UUID primary key swap

Revision ID: 7cc3fcc116c1
Revises: 16c37a30adf2
Create Date: 2025-09-22 09:54:38.292952

This migration performs the critical UUID primary key swap on user_file table.
It updates all foreign key references to use UUIDs instead of integers.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "7cc3fcc116c1"
down_revision = "16c37a30adf2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Swap user_file primary key from integer to UUID."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Verify we're in the expected state
    user_file_columns = [col["name"] for col in inspector.get_columns("user_file")]
    if "new_id" not in user_file_columns:
        logger.warning(
            "user_file.new_id not found - migration may have already been applied"
        )
        return

    logger.info("Starting UUID primary key swap...")

    # === Step 1: Update persona__user_file foreign key to UUID ===
    logger.info("Updating persona__user_file foreign key...")

    # Drop existing foreign key constraints
    op.execute(
        "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_uuid_fkey"
    )
    op.execute(
        "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_fkey"
    )

    # Create new foreign key to user_file.new_id
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        local_cols=["user_file_id_uuid"],
        remote_cols=["new_id"],
    )

    # Drop the old integer column and rename UUID column
    op.execute("ALTER TABLE persona__user_file DROP COLUMN IF EXISTS user_file_id")
    op.alter_column(
        "persona__user_file",
        "user_file_id_uuid",
        new_column_name="user_file_id",
        existing_type=psql.UUID(as_uuid=True),
        nullable=False,
    )

    # Recreate composite primary key
    op.execute(
        "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_pkey"
    )
    op.execute(
        "ALTER TABLE persona__user_file ADD PRIMARY KEY (persona_id, user_file_id)"
    )

    logger.info("Updated persona__user_file to use UUID foreign key")

    # === Step 2: Perform the primary key swap on user_file ===
    logger.info("Swapping user_file primary key to UUID...")

    # Drop the primary key constraint
    op.execute("ALTER TABLE user_file DROP CONSTRAINT IF EXISTS user_file_pkey")

    # Drop the old id column and rename new_id to id
    op.execute("ALTER TABLE user_file DROP COLUMN IF EXISTS id")
    op.alter_column(
        "user_file",
        "new_id",
        new_column_name="id",
        existing_type=psql.UUID(as_uuid=True),
        nullable=False,
    )

    # Set default for new inserts
    op.alter_column(
        "user_file",
        "id",
        existing_type=psql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
    )

    # Create new primary key
    op.execute("ALTER TABLE user_file ADD PRIMARY KEY (id)")

    logger.info("Swapped user_file primary key to UUID")

    # === Step 3: Update foreign key constraints ===
    logger.info("Updating foreign key constraints...")

    # Recreate persona__user_file foreign key to point to user_file.id
    # Drop existing FK first to break dependency on the unique constraint
    op.execute(
        "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_fkey"
    )
    # Drop the unique constraint on (formerly) new_id BEFORE recreating the FK,
    # so the FK will bind to the primary key instead of the unique index.
    op.execute("ALTER TABLE user_file DROP CONSTRAINT IF EXISTS uq_user_file_new_id")
    # Now recreate FK to the primary key column
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        local_cols=["user_file_id"],
        remote_cols=["id"],
    )

    # Add foreign keys for project__user_file
    existing_fks = inspector.get_foreign_keys("project__user_file")

    has_user_file_fk = any(
        fk.get("referred_table") == "user_file"
        and fk.get("constrained_columns") == ["user_file_id"]
        for fk in existing_fks
    )

    if not has_user_file_fk:
        op.create_foreign_key(
            "fk_project__user_file_user_file_id",
            "project__user_file",
            "user_file",
            ["user_file_id"],
            ["id"],
        )
        logger.info("Added project__user_file -> user_file foreign key")

    has_project_fk = any(
        fk.get("referred_table") == "user_project"
        and fk.get("constrained_columns") == ["project_id"]
        for fk in existing_fks
    )

    if not has_project_fk:
        op.create_foreign_key(
            "fk_project__user_file_project_id",
            "project__user_file",
            "user_project",
            ["project_id"],
            ["id"],
        )
        logger.info("Added project__user_file -> user_project foreign key")

    # === Step 4: Mark files for document_id migration ===
    logger.info("Marking files for background document_id migration...")

    logger.info("Migration 4 (UUID primary key swap) completed successfully")
    logger.info(
        "NOTE: Background task will update document IDs in Vespa and search_doc"
    )


def downgrade() -> None:
    """Revert UUID primary key back to integer (data destructive!)."""

    logger.error("CRITICAL: Downgrading UUID primary key swap is data destructive!")
    logger.error(
        "This will break all UUID-based references created after the migration."
    )
    logger.error("Only proceed if absolutely necessary and have backups.")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Capture existing primary key definitions so we can restore them after swaps
    persona_pk = inspector.get_pk_constraint("persona__user_file") or {}
    persona_pk_name = persona_pk.get("name")
    persona_pk_cols = persona_pk.get("constrained_columns") or []

    project_pk = inspector.get_pk_constraint("project__user_file") or {}
    project_pk_name = project_pk.get("name")
    project_pk_cols = project_pk.get("constrained_columns") or []

    # Drop foreign keys that reference the UUID primary key
    op.drop_constraint(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project__user_file_user_file_id",
        "project__user_file",
        type_="foreignkey",
    )

    # Drop primary keys that rely on the UUID column so we can replace it
    if persona_pk_name:
        op.drop_constraint(persona_pk_name, "persona__user_file", type_="primary")
    if project_pk_name:
        op.drop_constraint(project_pk_name, "project__user_file", type_="primary")

    # Rebuild integer IDs on user_file using a sequence-backed column
    op.execute("CREATE SEQUENCE IF NOT EXISTS user_file_id_seq")
    op.add_column(
        "user_file",
        sa.Column(
            "id_int",
            sa.Integer(),
            server_default=sa.text("nextval('user_file_id_seq')"),
            nullable=False,
        ),
    )
    op.execute("ALTER SEQUENCE user_file_id_seq OWNED BY user_file.id_int")

    # Prepare integer foreign key columns on referencing tables
    op.add_column(
        "persona__user_file",
        sa.Column("user_file_id_int", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project__user_file",
        sa.Column("user_file_id_int", sa.Integer(), nullable=True),
    )

    # Populate the new integer foreign key columns by mapping from the UUID IDs
    op.execute(
        """
        UPDATE persona__user_file AS p
        SET user_file_id_int = uf.id_int
        FROM user_file AS uf
        WHERE p.user_file_id = uf.id
        """
    )
    op.execute(
        """
        UPDATE project__user_file AS p
        SET user_file_id_int = uf.id_int
        FROM user_file AS uf
        WHERE p.user_file_id = uf.id
        """
    )

    op.alter_column(
        "persona__user_file",
        "user_file_id_int",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "project__user_file",
        "user_file_id_int",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Remove the UUID foreign key columns and rename the integer replacements
    op.drop_column("persona__user_file", "user_file_id")
    op.alter_column(
        "persona__user_file",
        "user_file_id_int",
        new_column_name="user_file_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_column("project__user_file", "user_file_id")
    op.alter_column(
        "project__user_file",
        "user_file_id_int",
        new_column_name="user_file_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Swap the user_file primary key back to the integer column
    op.drop_constraint("user_file_pkey", "user_file", type_="primary")
    op.drop_column("user_file", "id")
    op.alter_column(
        "user_file",
        "id_int",
        new_column_name="id",
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "user_file",
        "id",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("nextval('user_file_id_seq')"),
    )
    op.execute("ALTER SEQUENCE user_file_id_seq OWNED BY user_file.id")
    op.execute(
        """
        SELECT setval(
            'user_file_id_seq',
            GREATEST(COALESCE(MAX(id), 1), 1),
            MAX(id) IS NOT NULL
        )
        FROM user_file
        """
    )
    op.create_primary_key("user_file_pkey", "user_file", ["id"])

    # Restore primary keys on referencing tables
    if persona_pk_cols:
        op.create_primary_key(
            "persona__user_file_pkey", "persona__user_file", persona_pk_cols
        )
    if project_pk_cols:
        op.create_primary_key(
            "project__user_file_pkey",
            "project__user_file",
            project_pk_cols,
        )

    # Recreate foreign keys pointing at the integer primary key
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        ["user_file_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_project__user_file_user_file_id",
        "project__user_file",
        "user_file",
        ["user_file_id"],
        ["id"],
    )
