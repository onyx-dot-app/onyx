"""add chat_artifact_version version_reason

Revision ID: 78852b5a0db6
Revises: d6ab08737c37
Create Date: 2026-11-24 13:00:00.000000

Adds chat_artifact_version.version_reason, a short note on why the version
exists, which a replace, an update or a restore may give.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "78852b5a0db6"
down_revision = "d6ab08737c37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_artifact_version", sa.Column("version_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_artifact_version", "version_reason")
