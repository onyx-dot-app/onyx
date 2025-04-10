"""add persona categories

Revision ID: 47e5bef3a1d7
Revises: dfbe9e93d3c7
Create Date: 2024-11-05 18:55:02.221064

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "47e5bef3a1d7"
down_revision = "dfbe9e93d3c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the persona_category table
    op.create_table(
        "persona_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Add category_id to persona table
    op.add_column("persona", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_persona_category",
        "persona",
        "persona_category",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("persona_category_id_fkey", "persona", type_="foreignkey")
    op.drop_column("persona", "category_id")
    op.drop_table("persona_category")
