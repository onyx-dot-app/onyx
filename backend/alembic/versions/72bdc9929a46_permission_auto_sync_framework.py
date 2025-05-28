"""Permission Auto Sync Framework

Revision ID: 72bdc9929a46
Revises: 475fcefe8826
Create Date: 2024-04-14 21:15:28.659634

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "72bdc9929a46"
down_revision = "475fcefe8826"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("permission_sync_run")
    op.drop_table("external_permission")
    op.drop_table("email_to_external_user_cache")
