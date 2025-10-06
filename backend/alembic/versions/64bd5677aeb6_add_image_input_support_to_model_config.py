"""Add image input support to model config

Revision ID: 64bd5677aeb6
Revises: b30353be4eec
Create Date: 2025-09-28 15:48:12.003612

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "64bd5677aeb6"
down_revision = "b30353be4eec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column("supports_image_input", sa.Boolean(), nullable=True),
    )

    # Seems to be left over from when model visibility was introduced and a nullable field.
    # Set any null is_visible values to False
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE model_configuration SET is_visible = false WHERE is_visible IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "supports_image_input")
