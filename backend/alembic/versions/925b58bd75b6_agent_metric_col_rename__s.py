"""agent_metric_col_rename__s

Revision ID: 925b58bd75b6
Revises: 9787be927e58
Create Date: 2025-01-06 11:20:26.752441

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "925b58bd75b6"
down_revision = "9787be927e58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename columns using PostgreSQL syntax
    op.alter_column(
        "agent__search_metrics", "base_duration_s", new_column_name="base_duration__s"
    )
    op.alter_column(
        "agent__search_metrics", "full_duration_s", new_column_name="full_duration__s"
    )


def downgrade() -> None:
    # Revert the column renames
    op.alter_column(
        "agent__search_metrics", "base_duration__s", new_column_name="base_duration_s"
    )
    op.alter_column(
        "agent__search_metrics", "full_duration__s", new_column_name="full_duration_s"
    )
