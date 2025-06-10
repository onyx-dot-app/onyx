"""Add SyncRecord

Revision ID: 97dbb53fa8c8
Revises: 369644546676
Create Date: 2025-01-11 19:39:50.426302

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "97dbb53fa8c8"
down_revision = "be2ab2aa50ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "sync_type",
            sa.Enum(
                "DOCUMENT_SET",
                "USER_GROUP",
                "CONNECTOR_DELETION",
                name="synctype",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "sync_status",
            sa.Enum(
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                "CANCELED",
                name="syncstatus",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("num_docs_synced", sa.Integer(), nullable=False),
        sa.Column("sync_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_end_time", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add index for fetch_latest_sync_record query
    op.create_index(
        "ix_sync_record_entity_id_sync_type_sync_start_time",
        "sync_record",
        ["entity_id", "sync_type", "sync_start_time"],
    )

    # Add index for cleanup_sync_records query
    op.create_index(
        "ix_sync_record_entity_id_sync_type_sync_status",
        "sync_record",
        ["entity_id", "sync_type", "sync_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_record_entity_id_sync_type_sync_status")
    op.drop_index("ix_sync_record_entity_id_sync_type_sync_start_time")
    op.drop_table("sync_record")
