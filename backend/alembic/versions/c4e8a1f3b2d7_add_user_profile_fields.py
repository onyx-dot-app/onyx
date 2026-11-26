"""add user profile fields

`preferred_name` is the name Onyx calls the user. `profile_image_file_id`
references the profile photo in the file store.

Revision ID: c4e8a1f3b2d7
Revises: d5f9b2a4c3e8
Create Date: 2026-11-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e8a1f3b2d7"
down_revision = "d5f9b2a4c3e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("preferred_name", sa.String(), nullable=True))
    op.add_column(
        "user", sa.Column("profile_image_file_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user", "profile_image_file_id")
    op.drop_column("user", "preferred_name")
