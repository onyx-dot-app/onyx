"""agent_table_changes_rename_level

Revision ID: c0132518a25b
Revises: 1adf5ea20d2b
Create Date: 2025-01-05 16:38:37.660152

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c0132518a25b"
down_revision = "1adf5ea20d2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add level and level_question_nr columns with NOT NULL constraint
    op.add_column(
        "sub_question",
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sub_question",
        sa.Column(
            "level_question_nr", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    # Remove the server_default after the columns are created
    op.alter_column("sub_question", "level", server_default=None)
    op.alter_column("sub_question", "level_question_nr", server_default=None)


def downgrade() -> None:
    # Remove the columns
    op.drop_column("sub_question", "level_question_nr")
    op.drop_column("sub_question", "level")
