"""add review status to plugin versions

The published version of each plugin gets "published"; every other version
gets "draft". At most one version of a plugin is "pending".

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

_REVIEW_STATUSES = ("draft", "pending", "published", "denied", "superseded")


def upgrade() -> None:
    op.add_column(
        "plugin_version",
        sa.Column(
            "review_status",
            sa.Enum(*_REVIEW_STATUSES, native_enum=False),
            server_default="draft",
            nullable=False,
        ),
    )
    op.add_column(
        "plugin_version",
        sa.Column(
            "review_requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "user.id",
                name="plugin_version_review_requested_by_user_id_fkey",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "plugin_version",
        sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_plugin_version_one_pending",
        "plugin_version",
        ["plugin_id"],
        unique=True,
        postgresql_where=sa.text("review_status = 'pending'"),
    )
    op.execute(
        """
        UPDATE plugin_version
        SET review_status = 'published'
        FROM plugin
        WHERE plugin.published_version_id = plugin_version.id
        """
    )


def downgrade() -> None:
    op.drop_index("uq_plugin_version_one_pending", table_name="plugin_version")
    op.drop_column("plugin_version", "review_requested_at")
    op.drop_column("plugin_version", "review_requested_by_user_id")
    op.drop_column("plugin_version", "review_status")
