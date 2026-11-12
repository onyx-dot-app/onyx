"""add review status to plugin versions

Every version starts as "draft". At most one version of a plugin is
"pending". "Published" is not stored: it is the plugin's published_version_id.

Revision ID: 26ff9e3664f0
Revises: 7b154e670bd8
Create Date: 2026-11-11 21:30:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "26ff9e3664f0"
down_revision = "7b154e670bd8"
branch_labels = None
depends_on = None

_REVIEW_STATUSES = ("draft", "pending", "denied")


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
    op.create_index(
        "uq_plugin_version_one_pending",
        "plugin_version",
        ["plugin_id"],
        unique=True,
        postgresql_where=sa.text("review_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_plugin_version_one_pending", table_name="plugin_version")
    op.drop_column("plugin_version", "review_status")
