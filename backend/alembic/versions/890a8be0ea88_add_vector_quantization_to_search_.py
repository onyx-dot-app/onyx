"""add vector_quantization to search_settings

Revision ID: 890a8be0ea88
Revises: 25053020dd5a
Create Date: 2026-09-28 17:52:08.888885

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.enums import VectorQuantization

# revision identifiers, used by Alembic.
revision = "890a8be0ea88"
down_revision = "25053020dd5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing indices have no quantization in their mapping.
    op.add_column(
        "search_settings",
        sa.Column(
            "vector_quantization",
            sa.Enum(VectorQuantization, native_enum=False),
            nullable=False,
            server_default=VectorQuantization.NONE.name,
        ),
    )


def downgrade() -> None:
    op.drop_column("search_settings", "vector_quantization")
