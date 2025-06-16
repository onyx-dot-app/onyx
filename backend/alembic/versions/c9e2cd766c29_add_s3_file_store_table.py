"""modify_file_store_for_external_storage

Revision ID: c9e2cd766c29
Revises: cec7ec36c505
Create Date: 2025-06-13 14:02:09.867679

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import cast, Any

from onyx.db._deprecated.pg_file_store import delete_lobj_by_id, read_lobj
from onyx.file_store.file_store import get_s3_file_store

# revision identifiers, used by Alembic.
revision = "c9e2cd766c29"
down_revision = "cec7ec36c505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Modify existing file_store table to support external storage
    op.rename_table("file_store", "file_record")

    # Make lobj_oid nullable (for external storage files)
    op.alter_column("file_record", "lobj_oid", nullable=True)

    # Add external storage columns with generic names
    op.add_column("file_record", sa.Column("bucket_name", sa.String(), nullable=True))
    op.add_column("file_record", sa.Column("object_key", sa.String(), nullable=True))

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

    print(
        "External storage configured - migrating files from PostgreSQL to external storage..."
    )
    _migrate_files_to_external_storage()
    print("File migration completed successfully!")

    # Remove lobj_oid column
    op.drop_column("file_record", "lobj_oid")


def downgrade() -> None:
    # Note: This migration is not fully reversible if files have been migrated to external storage
    # The schema changes can be reverted, but files in external storage would need to be manually moved back
    print(
        "WARNING: This migration is not fully reversible if files were migrated to external storage."
    )
    print("Files in external storage will not be moved back to PostgreSQL.")

    op.rename_table("file_record", "file_store")

    # Remove external storage columns
    op.drop_column("file_store", "updated_at")
    op.drop_column("file_store", "created_at")
    op.drop_column("file_store", "object_key")
    op.drop_column("file_store", "bucket_name")

    # Make lobj_oid non-nullable again
    op.add_column("file_store", sa.Column("lobj_oid", sa.String(), nullable=True))


def _migrate_files_to_external_storage() -> None:
    """Migrate files from PostgreSQL large objects to external storage"""
    # Get database session
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        external_store = get_s3_file_store(db_session=session)

        # Find all files currently stored in PostgreSQL (lobj_oid is not null)
        result = session.execute(
            text("SELECT file_id FROM file_record WHERE lobj_oid IS NOT NULL")
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
            file_content = read_lobj(
                lobj_id, db_session=session, mode="b", use_tempfile=True
            )

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

        print(f"Migration completed: {migrated_count} files migrated successfully.")

    except Exception as e:
        print(f"Critical error during file migration: {str(e)}")
        session.rollback()
        raise e
    finally:
        session.close()
