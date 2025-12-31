"""add_is_auto_mode_to_llm_provider

Revision ID: 9a0296d7421e
Revises: 7206234e012a
Create Date: 2025-12-17 18:14:29.620981

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9a0296d7421e"
down_revision = "7206234e012a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_provider",
        sa.Column(
            "is_auto_mode",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_provider", "is_auto_mode")
