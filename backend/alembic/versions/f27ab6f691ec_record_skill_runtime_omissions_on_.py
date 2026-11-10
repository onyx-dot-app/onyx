"""Record Skill runtime omissions on sandboxes

Revision ID: f27ab6f691ec
Revises: 7655ce71767e
Create Date: 2026-11-08 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f27ab6f691ec"
down_revision = "7655ce71767e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox",
        sa.Column(
            "skill_runtime_omissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox", "skill_runtime_omissions")
