"""tag_type_column

Revision ID: 2a04911f3c9f
Revises: 62c3a055a141
Create Date: 2025-08-01 15:32:06.453072

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2a04911f3c9f"
down_revision = "62c3a055a141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tag",
        sa.Column(
            "tag_type",
            sa.Enum("single", "list", name="tagtype", native_enum=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tag", "tag_type")
