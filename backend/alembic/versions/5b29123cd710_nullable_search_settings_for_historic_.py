"""nullable search settings for historic index attempts

Revision ID: 5b29123cd710
Revises: 949b4a92a401
Create Date: 2024-10-30 19:37:59.630704

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5b29123cd710"
down_revision = "949b4a92a401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint
    op.drop_constraint(
        "fk_index_attempt_search_settings", "index_attempt", type_="foreignkey"
    )

    # Modify the column to be nullable
    op.alter_column(
        "index_attempt", "search_settings_id", existing_type=sa.INTEGER(), nullable=True
    )

    # Add back the foreign key with ON DELETE SET NULL
    op.create_foreign_key(
        "fk_index_attempt_search_settings",
        "index_attempt",
        "search_settings",
        ["search_settings_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Warning: This will delete all index attempts that don't have search settings
    op.execute(
        """
        DELETE FROM index_attempt
        WHERE search_settings_id IS NULL
    """
    )

    # Drop foreign key constraint
    op.drop_constraint(
        "fk_index_attempt_search_settings", "index_attempt", type_="foreignkey"
    )

    # Modify the column to be not nullable
    op.alter_column(
        "index_attempt",
        "search_settings_id",
        existing_type=sa.INTEGER(),
        nullable=False,
    )

    # Add back the foreign key without ON DELETE SET NULL
    op.create_foreign_key(
        "fk_index_attempt_search_settings",
        "index_attempt",
        "search_settings",
        ["search_settings_id"],
        ["id"],
    )
