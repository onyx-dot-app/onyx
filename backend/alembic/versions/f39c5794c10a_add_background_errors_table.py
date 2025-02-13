"""Add background errors table

Revision ID: f39c5794c10a
Revises: 2cdeff6d8c93
Create Date: 2025-02-12 17:11:14.527876

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f39c5794c10a"
down_revision = "2cdeff6d8c93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("background_errors")
