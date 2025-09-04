"""drop include citations

Revision ID: 8818cf73fa1a
Revises: 7ed603b64d5a
Create Date: 2025-09-02 19:43:50.060680

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8818cf73fa1a"
down_revision = "7ed603b64d5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("prompt", "include_citations")


def downgrade() -> None:
    op.add_column(
        "prompt",
        sa.Column(
            "include_citations",
            sa.BOOLEAN(),
            autoincrement=False,
            nullable=True,
        ),
    )
    # Set include_citations based on prompt name: FALSE for ImageGeneration, TRUE for others
    op.execute(
        sa.text(
            "UPDATE prompt SET include_citations = CASE WHEN name = 'ImageGeneration' THEN FALSE ELSE TRUE END"
        )
    )
