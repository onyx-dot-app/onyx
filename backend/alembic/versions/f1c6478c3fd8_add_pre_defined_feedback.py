"""Add pre-defined feedback

Revision ID: f1c6478c3fd8
Revises: 643a84a42a33
Create Date: 2024-05-09 18:11:49.210667

"""

from alembic import op
import sqlalchemy as sa

revision = "f1c6478c3fd8"
down_revision = "643a84a42a33"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_feedback",
        sa.Column("predefined_feedback", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_feedback", "predefined_feedback")
