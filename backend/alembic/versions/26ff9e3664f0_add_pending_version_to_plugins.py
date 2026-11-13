"""add pending version to plugins

``plugin.pending_version_id`` is the version waiting for an admin's review.

Revision ID: 26ff9e3664f0
Revises: 7b154e670bd8
Create Date: 2026-11-11 21:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "26ff9e3664f0"
down_revision = "7b154e670bd8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugin",
        sa.Column("pending_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_plugin_pending_version",
        "plugin",
        "plugin_version",
        ["pending_version_id", "id"],
        ["id", "plugin_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_plugin_pending_version", "plugin", type_="foreignkey")
    op.drop_column("plugin", "pending_version_id")
