"""Add time_updated to UserGroup and DocumentSet

Revision ID: fec3db967bf7
Revises: 97dbb53fa8c8
Create Date: 2025-01-12 15:49:02.289100

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fec3db967bf7"
down_revision = "97dbb53fa8c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_set",
        sa.Column(
            "time_last_modified_by_user",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "user_group",
        sa.Column(
            "time_last_modified_by_user",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_group", "time_last_modified_by_user")
    op.drop_column("document_set", "time_last_modified_by_user")
