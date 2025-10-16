"""add permission sync attempt tables

Revision ID: 03d710ccf29c
Revises: 96a5702df6aa
Create Date: 2025-09-11 13:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "03d710ccf29c"  # Generate a new unique ID
down_revision = "96a5702df6aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the permission sync status enum
    permission_sync_status_enum = sa.Enum(
        "not_started",
        "in_progress",
        "success",
        "canceled",
        "failed",
        "completed_with_errors",
        name="permissionsyncstatus",
        native_enum=False,
    )

    # Create doc_permission_sync_attempt table
    op.create_table(
        "doc_permission_sync_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("status", permission_sync_status_enum, nullable=False),
        sa.Column("total_docs_synced", sa.Integer(), nullable=True),
        sa.Column("docs_with_permission_errors", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("time_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_finished", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for doc_permission_sync_attempt
    op.create_index(
        "ix_doc_permission_sync_attempt_time_created",
        "doc_permission_sync_attempt",
        ["time_created"],
        unique=False,
    )
    op.create_index(
        "ix_permission_sync_attempt_latest_for_cc_pair",
        "doc_permission_sync_attempt",
        ["connector_credential_pair_id", "time_created"],
        unique=False,
    )
    op.create_index(
        "ix_permission_sync_attempt_status_time",
        "doc_permission_sync_attempt",
        ["status", sa.text("time_finished DESC")],
        unique=False,
    )

    # Create external_group_permission_sync_attempt table
    # connector_credential_pair_id is nullable - group syncs can be global (e.g., Confluence)
    op.create_table(
        "external_group_permission_sync_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=True),
        sa.Column("status", permission_sync_status_enum, nullable=False),
        sa.Column("total_users_processed", sa.Integer(), nullable=True),
        sa.Column("total_groups_processed", sa.Integer(), nullable=True),
        sa.Column("total_group_memberships_synced", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("time_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_finished", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for external_group_permission_sync_attempt
    op.create_index(
        "ix_external_group_permission_sync_attempt_time_created",
        "external_group_permission_sync_attempt",
        ["time_created"],
        unique=False,
    )
    op.create_index(
        "ix_group_sync_attempt_cc_pair_time",
        "external_group_permission_sync_attempt",
        ["connector_credential_pair_id", "time_created"],
        unique=False,
    )
    op.create_index(
        "ix_group_sync_attempt_status_time",
        "external_group_permission_sync_attempt",
        ["status", sa.text("time_finished DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index(
        "ix_group_sync_attempt_status_time",
        table_name="external_group_permission_sync_attempt",
    )
    op.drop_index(
        "ix_group_sync_attempt_cc_pair_time",
        table_name="external_group_permission_sync_attempt",
    )
    op.drop_index(
        "ix_external_group_permission_sync_attempt_time_created",
        table_name="external_group_permission_sync_attempt",
    )
    op.drop_index(
        "ix_permission_sync_attempt_status_time",
        table_name="doc_permission_sync_attempt",
    )
    op.drop_index(
        "ix_permission_sync_attempt_latest_for_cc_pair",
        table_name="doc_permission_sync_attempt",
    )
    op.drop_index(
        "ix_doc_permission_sync_attempt_time_created",
        table_name="doc_permission_sync_attempt",
    )

    # Drop tables
    op.drop_table("external_group_permission_sync_attempt")
    op.drop_table("doc_permission_sync_attempt")
