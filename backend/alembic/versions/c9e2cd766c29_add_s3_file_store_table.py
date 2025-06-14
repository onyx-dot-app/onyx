"""modify_file_store_for_external_storage

Revision ID: c9e2cd766c29
Revises: cec7ec36c505
Create Date: 2025-06-13 14:02:09.867679

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "c9e2cd766c29"
down_revision = "cec7ec36c505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Modify existing file_store table to support external storage

    # Make lobj_oid nullable (for external storage files)
    op.alter_column("file_store", "lobj_oid", nullable=True)

    # Add external storage columns with generic names
    op.add_column("file_store", sa.Column("bucket_name", sa.String(), nullable=True))
    op.add_column("file_store", sa.Column("object_key", sa.String(), nullable=True))

    # Add timestamps for tracking
    op.add_column(
        "file_store",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "file_store",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add constraint to ensure either lobj_oid OR (bucket_name AND object_key) is set
    op.create_check_constraint(
        "file_store_storage_check",
        "file_store",
        "(lobj_oid IS NOT NULL) OR (bucket_name IS NOT NULL AND object_key IS NOT NULL)",
    )

    print(
        "External storage configured - migrating files from PostgreSQL to external storage..."
    )
    _migrate_files_to_external_storage()
    print("File migration completed successfully!")


def downgrade() -> None:
    # Note: This migration is not fully reversible if files have been migrated to external storage
    # The schema changes can be reverted, but files in external storage would need to be manually moved back
    print(
        "WARNING: This migration is not fully reversible if files were migrated to external storage."
    )
    print("Files in external storage will not be moved back to PostgreSQL.")

    # Remove the check constraint
    op.drop_constraint("file_store_storage_check", "file_store")

    # Remove external storage columns
    op.drop_column("file_store", "updated_at")
    op.drop_column("file_store", "created_at")
    op.drop_column("file_store", "object_key")
    op.drop_column("file_store", "bucket_name")

    # Make lobj_oid non-nullable again
    op.alter_column("file_store", "lobj_oid", nullable=False)


def _migrate_files_to_external_storage() -> None:
    """Migrate files from PostgreSQL large objects to external storage"""
    # Get database session
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Import file store classes for the migration
        from onyx.file_store._deprecated.postgres_file_store import (
            PostgresBackedFileStore,
        )
        from onyx.file_store.file_store import S3BackedFileStore

        # Create file store instances
        postgres_store = PostgresBackedFileStore(db_session=session)
        external_store = S3BackedFileStore(db_session=session)

        # Find all files currently stored in PostgreSQL (lobj_oid is not null)
        result = session.execute(
            text("SELECT file_name FROM file_store WHERE lobj_oid IS NOT NULL")
        )

        files_to_migrate = [row[0] for row in result.fetchall()]
        total_files = len(files_to_migrate)

        if total_files == 0:
            print("No files found in PostgreSQL storage to migrate.")
            return

        print(
            f"Found {total_files} files to migrate from PostgreSQL to external storage."
        )

        migrated_count = 0
        failed_count = 0

        for i, file_name in enumerate(files_to_migrate, 1):
            try:
                print(f"Migrating file {i}/{total_files}: {file_name}")

                # Read file record to get metadata
                file_record = postgres_store.read_file_record(file_name)

                # Read file content from PostgreSQL
                file_content = postgres_store.read_file(file_name, mode="b")

                # Handle file_metadata type conversion
                file_metadata = None
                if file_record.file_metadata is not None:
                    if isinstance(file_record.file_metadata, dict):
                        file_metadata = file_record.file_metadata
                    else:
                        # Convert other types to dict if possible, otherwise None
                        try:
                            file_metadata = dict(file_record.file_metadata)  # type: ignore
                        except (TypeError, ValueError):
                            file_metadata = None

                # Save to external storage (this will handle the database record update and cleanup)
                external_store.save_file(
                    file_name=file_record.file_name,
                    content=file_content,
                    display_name=file_record.display_name,
                    file_origin=file_record.file_origin,
                    file_type=file_record.file_type,
                    file_metadata=file_metadata,
                )

                migrated_count += 1
                print(f"✓ Successfully migrated file {i}/{total_files}: {file_name}")

            except Exception as e:
                failed_count += 1
                print(f"✗ Failed to migrate file {file_name}: {str(e)}")
                # Continue with other files rather than failing the entire migration
                session.rollback()

        print(
            f"Migration completed: {migrated_count} files migrated successfully, {failed_count} files failed."
        )

        if failed_count > 0:
            print("Some files failed to migrate. Check the logs above for details.")
            print(
                "Failed files remain in PostgreSQL storage and can be migrated manually later."
            )

    except Exception as e:
        print(f"Critical error during file migration: {str(e)}")
        session.rollback()
        raise e
    finally:
        session.close()
