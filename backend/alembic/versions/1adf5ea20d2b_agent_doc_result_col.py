"""agent_doc_result_col

Revision ID: 1adf5ea20d2b
Revises: e9cf2bd7baed
Create Date: 2025-01-05 13:14:58.344316

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1adf5ea20d2b"
down_revision = "e9cf2bd7baed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the new column with JSONB type
    op.add_column(
        "sub_question",
        sa.Column("sub_question_doc_results", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # Drop the column
    op.drop_column("sub_question", "sub_question_doc_results")
