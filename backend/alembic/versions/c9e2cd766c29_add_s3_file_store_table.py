"""modify_file_store_for_external_storage

Revision ID: c9e2cd766c29
Revises: 03bf8be6b53a
Create Date: 2025-06-13 14:02:09.867679

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import cast, Any

from botocore.exceptions import ClientError

from onyx.db._deprecated.pg_file_store import delete_lobj_by_id, read_lobj
from onyx.file_store.file_store import get_s3_file_store
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# revision identifiers, used by Alembic.
revision = "c9e2cd766c29"
down_revision = "03bf8be6b53a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        # Modify existing file_store table to support external storage
        op.rename_table("file_store", "file_record")

        # Make lobj_oid nullable (for external storage files)
        op.alter_column("file_record", "lobj_oid", nullable=True)

        # Add external storage columns with generic names
        op.add_column(
            "file_record", sa.Column("bucket_name", sa.String(), nullable=True)
        )
        op.add_column(
            "file_record", sa.Column("object_key", sa.String(), nullable=True)
        )

        # Add timestamps for tracking
        op.add_column(
            "file_record",
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.add_column(
            "file_record",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

        op.alter_column("file_record", "file_name", new_column_name="file_id")
    except Exception as e:
        if "does not exist" in str(e) or 'relation "file_store" does not exist' in str(
            e
        ):
            print(
                f"Ran into error - {e}. Likely means we had a partial success in the past, continuing..."
            )
        else:
            raise

    print(
        "External storage configured - migrating files from PostgreSQL to external storage..."
    )
    # if we fail midway through this, we'll have a partial success. Running the migration
    # again should allow us to continue.
    _migrate_files_to_external_storage()
    print("File migration completed successfully!")

    # Remove lobj_oid column
    op.drop_column("file_record", "lobj_oid")


def downgrade() -> None:
    """Revert schema changes and migrate files from external storage back to PostgreSQL large objects."""

    print(
        "Reverting to PostgreSQL-backed file store – migrating files from external storage …"
    )

    # 1. Ensure `lobj_oid` exists on the current `file_record` table (nullable for now).
    op.add_column("file_record", sa.Column("lobj_oid", sa.Integer(), nullable=True))

    # 2. Move content from external storage back into PostgreSQL large objects (table is still
    #    called `file_record` so application code continues to work during the copy).
    try:
        _migrate_files_to_postgres()
    except Exception:
        print("Error during downgrade migration, rolling back …")
        op.drop_column("file_record", "lobj_oid")
        raise

    # 3. After migration every row should now have `lobj_oid` populated – mark NOT NULL.
    op.alter_column("file_record", "lobj_oid", nullable=False)

    # 4. Remove columns that are only relevant to external storage.
    op.drop_column("file_record", "updated_at")
    op.drop_column("file_record", "created_at")
    op.drop_column("file_record", "object_key")
    op.drop_column("file_record", "bucket_name")

    # 5. Rename `file_id` back to `file_name` (still on `file_record`).
    op.alter_column("file_record", "file_id", new_column_name="file_name")

    # 6. Finally, rename the table back to its original name expected by the legacy codebase.
    op.rename_table("file_record", "file_store")

    print(
        "Downgrade migration completed – files are now stored inside PostgreSQL again."
    )


# -----------------------------------------------------------------------------
# Helper: migrate from external storage (S3/MinIO) back into PostgreSQL large objects


def _migrate_files_to_postgres() -> None:
    """Move any files whose content lives in external S3-compatible storage back into PostgreSQL.

    The logic mirrors *inverse* of `_migrate_files_to_external_storage` used on upgrade.
    """

    # Obtain DB session from Alembic context
    bind = op.get_bind()
    session = Session(bind=bind)

    # Fetch rows that have external storage pointers (bucket/object_key not NULL)
    result = session.execute(
        text(
            "SELECT file_id, bucket_name, object_key FROM file_record "
            "WHERE bucket_name IS NOT NULL AND object_key IS NOT NULL"
        )
    )

    files_to_migrate = [row[0] for row in result.fetchall()]
    total_files = len(files_to_migrate)

    if total_files == 0:
        print("No files found in external storage to migrate back to PostgreSQL.")
        return

    print(f"Found {total_files} files to migrate back to PostgreSQL large objects.")

    _set_tenant_contextvar(session)
    migrated_count = 0

    # only create external store if we have files to migrate. This line
    # makes it so we need to have S3/MinIO configured to run this migration.
    external_store = get_s3_file_store()

    for i, file_id in enumerate(files_to_migrate, 1):
        print(f"Migrating file {i}/{total_files}: {file_id}")

        # Read file content from external storage (always binary)
        try:
            file_io = external_store.read_file(
                file_id=file_id, mode="b", use_tempfile=True
            )
            file_io.seek(0)

            # Import lazily to avoid circular deps at Alembic runtime
            from onyx.db._deprecated.pg_file_store import (
                create_populate_lobj,
            )  # noqa: E402

            # Create new Postgres large object and populate it
            lobj_oid = create_populate_lobj(content=file_io, db_session=session)

            # Update DB row: set lobj_oid, clear bucket/object_key
            session.execute(
                text(
                    "UPDATE file_record SET lobj_oid = :lobj_oid, bucket_name = NULL, "
                    "object_key = NULL WHERE file_id = :file_id"
                ),
                {"lobj_oid": lobj_oid, "file_id": file_id},
            )
        except ClientError as e:
            if "NoSuchKey" in str(e):
                print(
                    f"File {file_id} not found in external storage. Deleting from database."
                )
                session.execute(
                    text("DELETE FROM file_record WHERE file_id = :file_id"),
                    {"file_id": file_id},
                )
            else:
                raise

        migrated_count += 1
        print(f"✓ Successfully migrated file {i}/{total_files}: {file_id}")

    # Flush the SQLAlchemy session so statements are sent to the DB, but **do not**
    # commit the transaction.  The surrounding Alembic migration will commit once
    # the *entire* downgrade succeeds.  This keeps the whole downgrade atomic and
    # avoids leaving the database in a partially-migrated state if a later schema
    # operation fails.
    session.flush()

    print(
        f"Migration back to PostgreSQL completed: {migrated_count} files staged for commit."
    )


def _migrate_files_to_external_storage() -> None:
    """Migrate files from PostgreSQL large objects to external storage"""
    # Get database session
    bind = op.get_bind()
    session = Session(bind=bind)
    external_store = get_s3_file_store()

    # Find all files currently stored in PostgreSQL (lobj_oid is not null)
    result = session.execute(
        text(
            "SELECT file_id FROM file_record WHERE lobj_oid IS NOT NULL "
            "AND bucket_name IS NULL AND object_key IS NULL"
        )
    )

    files_to_migrate = [row[0] for row in result.fetchall()]
    total_files = len(files_to_migrate)

    if total_files == 0:
        print("No files found in PostgreSQL storage to migrate.")
        return

    # might need to move this above the if statement when creating a new multi-tenant
    # system. VERY extreme edge case.
    external_store.initialize()
    print(f"Found {total_files} files to migrate from PostgreSQL to external storage.")

    _set_tenant_contextvar(session)
    migrated_count = 0

    for i, file_id in enumerate(files_to_migrate, 1):
        print(f"Migrating file {i}/{total_files}: {file_id}")

        # Read file record to get metadata
        file_record = session.execute(
            text("SELECT * FROM file_record WHERE file_id = :file_id"),
            {"file_id": file_id},
        ).fetchone()

        if file_record is None:
            print(f"File {file_id} not found in PostgreSQL storage.")
            continue

        lobj_id = cast(int, file_record.lobj_oid)  # type: ignore
        file_metadata = cast(Any, file_record.file_metadata)  # type: ignore

        # Read file content from PostgreSQL
        try:
            file_content = read_lobj(
                lobj_id, db_session=session, mode="b", use_tempfile=True
            )
        except Exception as e:
            if "large object" in str(e) and "does not exist" in str(e):
                print(f"File {file_id} not found in PostgreSQL storage.")
                continue
            else:
                raise

        # Handle file_metadata type conversion
        file_metadata = None
        if file_metadata is not None:
            if isinstance(file_metadata, dict):
                file_metadata = file_metadata
            else:
                # Convert other types to dict if possible, otherwise None
                try:
                    file_metadata = dict(file_record.file_metadata)  # type: ignore
                except (TypeError, ValueError):
                    file_metadata = None

        # Save to external storage (this will handle the database record update and cleanup)
        # NOTE: this WILL .commit() the transaction.
        external_store.save_file(
            file_id=file_id,
            content=file_content,
            display_name=file_record.display_name,
            file_origin=file_record.file_origin,
            file_type=file_record.file_type,
            file_metadata=file_metadata,
        )
        delete_lobj_by_id(lobj_id, db_session=session)

        migrated_count += 1
        print(f"✓ Successfully migrated file {i}/{total_files}: {file_id}")

    # See note above – flush but do **not** commit so the outer Alembic transaction
    # controls atomicity.
    session.flush()

    print(
        f"Migration completed: {migrated_count} files staged for commit to external storage."
    )


def _set_tenant_contextvar(session: Session) -> None:
    """Set the tenant contextvar to the default schema"""
    current_tenant = session.execute(text("SELECT current_schema()")).scalar()
    print(f"Migrating files for tenant: {current_tenant}")
    CURRENT_TENANT_ID_CONTEXTVAR.set(current_tenant)
