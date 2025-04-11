"""Add full exception stack trace

Revision ID: 8987770549c0
Revises: ec3ec2eabf7b
Create Date: 2024-02-10 19:31:28.339135

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8987770549c0"
down_revision = "ec3ec2eabf7b"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "index_attempt", sa.Column("full_exception_trace", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "full_exception_trace")
