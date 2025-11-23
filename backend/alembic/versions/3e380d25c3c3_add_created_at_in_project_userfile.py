"""add_created_at_in_project_userfile

Revision ID: 3e380d25c3c3
Revises: 1f2a3b4c5d6e
Create Date: 2025-11-19 14:10:49.515889

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3e380d25c3c3"
down_revision = "1f2a3b4c5d6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add created_at column to project__user_file table
    op.add_column(
        "project__user_file",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Add index on created_at column
    op.create_index(
        "ix_project__user_file_created_at",
        "project__user_file",
        ["created_at"],
    )


def downgrade() -> None:
    # Remove index on created_at column
    op.drop_index("ix_project__user_file_created_at", table_name="project__user_file")
    # Remove created_at column from project__user_file table
    op.drop_column("project__user_file", "created_at")
