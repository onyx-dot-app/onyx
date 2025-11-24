"""add_created_at_in_project_userfile

Revision ID: 6436661d5b65
Revises: c7e9f4a3b2d1
Create Date: 2025-11-24 11:50:24.536052

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6436661d5b65"
down_revision = "c7e9f4a3b2d1"
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
    # Add composite index on (project_id, created_at DESC)
    op.create_index(
        "ix_project__user_file_project_id_created_at",
        "project__user_file",
        ["project_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # Remove composite index on (project_id, created_at)
    op.drop_index(
        "ix_project__user_file_project_id_created_at", table_name="project__user_file"
    )
    # Remove created_at column from project__user_file table
    op.drop_column("project__user_file", "created_at")
