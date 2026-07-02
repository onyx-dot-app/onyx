"""add external group sync errors

Revision ID: 8a4f1c2d3e5b
Revises: 7f2a3b9c1d4e
Create Date: 2026-07-02 10:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8a4f1c2d3e5b"
down_revision = "7f2a3b9c1d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_group_sync_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_group_sync_attempt_id", sa.Integer(), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("external_group_id", sa.String(), nullable=True),
        sa.Column("external_group_name", sa.String(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("full_exception_trace", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_group_sync_attempt_id"],
            ["external_group_permission_sync_attempt.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_group_sync_errors_connector_credential_pair_id",
        "external_group_sync_errors",
        ["connector_credential_pair_id"],
    )
    op.create_index(
        "ix_external_group_sync_errors_external_group_sync_attempt_id",
        "external_group_sync_errors",
        ["external_group_sync_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_group_sync_errors_external_group_sync_attempt_id",
        table_name="external_group_sync_errors",
    )
    op.drop_index(
        "ix_external_group_sync_errors_connector_credential_pair_id",
        table_name="external_group_sync_errors",
    )
    op.drop_table("external_group_sync_errors")
