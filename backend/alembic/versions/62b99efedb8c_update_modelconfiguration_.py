"""update ModelConfiguration recommendation fields to boolean

Revision ID: 62b99efedb8c
Revises: 0816326d83aa
Create Date: 2025-07-15 14:30:13.501302

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "62b99efedb8c"
down_revision = "0816326d83aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the boolean recommendation columns
    op.add_column(
        "model_configuration",
        sa.Column(
            "recommended_default",
            sa.Boolean(),
            nullable=True,
            default=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "model_configuration",
        sa.Column(
            "recommended_fast_default",
            sa.Boolean(),
            nullable=True,
            default=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "model_configuration",
        sa.Column(
            "recommended_is_visible",
            sa.Boolean(),
            nullable=True,
            default=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # Remove the boolean recommendation columns
    op.drop_column("model_configuration", "recommended_fast_default")
    op.drop_column("model_configuration", "recommended_default")
    op.drop_column("model_configuration", "recommended_is_visible")
