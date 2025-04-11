"""duplicated no-harm user file migration

Revision ID: 6a804aeb4830
Revises: 8e1ac4f39a9f
Create Date: 2025-04-01 07:26:10.539362

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
import datetime


# revision identifiers, used by Alembic.
revision = "6a804aeb4830"
down_revision = "8e1ac4f39a9f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if user_file table already exists
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("user_file"):
        # Create user_folder table without parent_id
        op.create_table(
            "user_folder",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("display_priority", sa.Integer(), nullable=True, default=0),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

        # Create user_file table with folder_id instead of parent_folder_id
        op.create_table(
            "user_file",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column(
                "folder_id",
                sa.Integer(),
                sa.ForeignKey("user_folder.id"),
                nullable=True,
            ),
            sa.Column("link_url", sa.String(), nullable=True),
            sa.Column("token_count", sa.Integer(), nullable=True),
            sa.Column("file_type", sa.String(), nullable=True),
            sa.Column("file_id", sa.String(length=255), nullable=False),
            sa.Column("document_id", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                default=datetime.datetime.utcnow,
            ),
            sa.Column(
                "cc_pair_id",
                sa.Integer(),
                sa.ForeignKey("connector_credential_pair.id"),
                nullable=True,
                unique=True,
            ),
        )

        # Create persona__user_file table
        op.create_table(
            "persona__user_file",
            sa.Column(
                "persona_id",
                sa.Integer(),
                sa.ForeignKey("persona.id"),
                primary_key=True,
            ),
            sa.Column(
                "user_file_id",
                sa.Integer(),
                sa.ForeignKey("user_file.id"),
                primary_key=True,
            ),
        )

        # Create persona__user_folder table
        op.create_table(
            "persona__user_folder",
            sa.Column(
                "persona_id",
                sa.Integer(),
                sa.ForeignKey("persona.id"),
                primary_key=True,
            ),
            sa.Column(
                "user_folder_id",
                sa.Integer(),
                sa.ForeignKey("user_folder.id"),
                primary_key=True,
            ),
        )

        op.add_column(
            "connector_credential_pair",
            sa.Column("is_user_file", sa.Boolean(), nullable=True, default=False),
        )

        # Update existing records to have is_user_file=False instead of NULL
        op.execute(
            "UPDATE connector_credential_pair SET is_user_file = FALSE WHERE is_user_file IS NULL"
        )


def downgrade() -> None:
    pass
