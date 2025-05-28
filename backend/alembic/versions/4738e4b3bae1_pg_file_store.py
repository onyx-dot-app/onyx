"""PG File Store

Revision ID: 4738e4b3bae1
Revises: e91df4e935ef
Create Date: 2024-03-20 18:53:32.461518

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4738e4b3bae1"
down_revision = "e91df4e935ef"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "file_store",
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("lobj_oid", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("file_name"),
    )


def downgrade() -> None:
    op.drop_table("file_store")
