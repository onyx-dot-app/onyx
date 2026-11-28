"""add processing_attempts to user_file

Counts pickups of a user file by the processing task so a file whose worker
keeps dying mid-file is marked FAILED instead of re-enqueued forever.

Revision ID: a7a7e8c828c0
Revises: 859be0a5310b
Create Date: 2026-10-30 12:00:04.262001

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7a7e8c828c0"
down_revision = "859be0a5310b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_file",
        sa.Column(
            "processing_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("user_file", "processing_attempts")
