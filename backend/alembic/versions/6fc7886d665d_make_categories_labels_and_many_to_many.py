"""make categories labels and many to many

Revision ID: 6fc7886d665d
Revises: 3c6531f32351
Create Date: 2025-01-13 18:12:18.029112

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6fc7886d665d"
down_revision = "3c6531f32351"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename persona_category table to persona_label
    op.rename_table("persona_category", "persona_label")

    # Create the new association table
    op.create_table(
        "persona__persona_label",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("persona_label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(
            ["persona_label_id"],
            ["persona_label.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("persona_id", "persona_label_id"),
    )

    # Copy existing relationships to the new table
    op.execute(
        """
        INSERT INTO persona__persona_label (persona_id, persona_label_id)
        SELECT id, category_id FROM persona WHERE category_id IS NOT NULL
    """
    )

    # Remove the old category_id column from persona table
    op.drop_column("persona", "category_id")


def downgrade() -> None:
    # Rename persona_label table back to persona_category
    op.rename_table("persona_label", "persona_category")

    # Add back the category_id column to persona table
    op.add_column("persona", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "persona_category_id_fkey",
        "persona",
        "persona_category",
        ["category_id"],
        ["id"],
    )

    # Copy the first label relationship back to the persona table
    op.execute(
        """
        UPDATE persona
        SET category_id = (
            SELECT persona_label_id
            FROM persona__persona_label
            WHERE persona__persona_label.persona_id = persona.id
            LIMIT 1
        )
    """
    )

    # Drop the association table
    op.drop_table("persona__persona_label")
