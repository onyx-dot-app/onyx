"""resolve automatic skill names at runtime

Revision ID: 54013115725e
Revises: 0194658d026d
Create Date: 2026-11-08 05:05:04.736838

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "54013115725e"
down_revision = "0194658d026d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_skill_automatic_name", table_name="skill")


def downgrade() -> None:
    """Require the duplicate-name preflight in the admin Skills guide."""
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text(
            "installation_policy <> 'AVAILABLE' AND retired_at IS NULL"
        ),
    )
