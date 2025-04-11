"""Add Permission Syncing

Revision ID: 61ff3651add4
Revises: 1b8206b29c5d
Create Date: 2024-09-05 13:57:11.770413

"""

import fastapi_users_db_sqlalchemy

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "61ff3651add4"
down_revision = "1b8206b29c5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Admin user who set up connectors will lose access to the docs temporarily
    # only way currently to give back access is to rerun from beginning
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "access_type",
            sa.String(),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE connector_credential_pair SET access_type = 'PUBLIC' WHERE is_public = true"
    )
    op.execute(
        "UPDATE connector_credential_pair SET access_type = 'PRIVATE' WHERE is_public = false"
    )
    op.alter_column("connector_credential_pair", "access_type", nullable=False)

    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "auto_sync_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "connector_credential_pair",
        sa.Column("last_time_perm_sync", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("connector_credential_pair", "is_public")

    op.add_column(
        "document",
        sa.Column("external_user_emails", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column(
            "external_user_group_ids", postgresql.ARRAY(sa.String()), nullable=True
        ),
    )
    op.add_column(
        "document",
        sa.Column("is_public", sa.Boolean(), nullable=True),
    )

    op.create_table(
        "user__external_user_group_id",
        sa.Column(
            "user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False
        ),
        sa.Column("external_user_group_id", sa.String(), nullable=False),
        sa.Column("cc_pair_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.drop_column("external_permission", "user_id")
    op.drop_column("email_to_external_user_cache", "user_id")
    op.drop_table("permission_sync_run")
    op.drop_table("external_permission")
    op.drop_table("email_to_external_user_cache")


def downgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column("is_public", sa.BOOLEAN(), nullable=True),
    )
    op.execute(
        "UPDATE connector_credential_pair SET is_public = (access_type = 'PUBLIC')"
    )
    op.alter_column("connector_credential_pair", "is_public", nullable=False)

    op.drop_column("connector_credential_pair", "auto_sync_options")
    op.drop_column("connector_credential_pair", "access_type")
    op.drop_column("connector_credential_pair", "last_time_perm_sync")
    op.drop_column("document", "external_user_emails")
    op.drop_column("document", "external_user_group_ids")
    op.drop_column("document", "is_public")

    op.drop_table("user__external_user_group_id")

    # Drop the enum type at the end of the downgrade
    op.create_table(
        "permission_sync_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "source_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column("update_type", sa.String(), nullable=False),
        sa.Column("cc_pair_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
        ),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cc_pair_id"],
            ["connector_credential_pair.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "external_permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column(
            "source_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column("external_permission_group", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "email_to_external_user_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_user_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
