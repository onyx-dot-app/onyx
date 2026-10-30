"""add llm_provider_owned to image_generation_config

Existing configs own a copy of an LLM provider. Linked configs point at a
model on an admin-managed provider and set this to false.

Revision ID: b7d2e4f1a9c3
Revises: ca7cc9a98a6b
Create Date: 2026-10-30 11:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7d2e4f1a9c3"
down_revision = "ca7cc9a98a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "image_generation_config",
        sa.Column(
            "llm_provider_owned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("image_generation_config", "llm_provider_owned")
