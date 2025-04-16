"""Index From Beginning

Revision ID: ec3ec2eabf7b
Revises: dbaa756c2ccf
Create Date: 2024-02-06 22:03:28.098158

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ec3ec2eabf7b"
down_revision = "dbaa756c2ccf"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "index_attempt", sa.Column("from_beginning", sa.Boolean(), nullable=True)
    )
    op.execute("UPDATE index_attempt SET from_beginning = False")
    op.alter_column("index_attempt", "from_beginning", nullable=False)


def downgrade() -> None:
    op.drop_column("index_attempt", "from_beginning")
