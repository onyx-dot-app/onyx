"""add model_cost_override

Revision ID: a7f3e2c1b9d4
Revises: c4e1a9f7b2d8
Create Date: 2026-06-03 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7f3e2c1b9d4"
down_revision = "c4e1a9f7b2d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_cost_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_cost_per_mtok", sa.Float(), nullable=False),
        sa.Column("output_cost_per_mtok", sa.Float(), nullable=False),
        # The model's onupdate=func.now() is ORM-side only (not DDL), so
        # updated_at auto-bumps on ORM writes but not on raw-SQL UPDATEs.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model", name="uq_model_cost_override_model"),
    )


def downgrade() -> None:
    op.drop_table("model_cost_override")
