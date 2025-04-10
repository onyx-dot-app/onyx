"""Remove DocumentSource from Tag

Revision ID: 91fd3b470d1a
Revises: 173cae5bba26
Create Date: 2024-03-21 12:05:23.956734

"""

from alembic import op
import sqlalchemy as sa
from onyx.configs.constants import DocumentSource

# revision identifiers, used by Alembic.
revision = "91fd3b470d1a"
down_revision = "173cae5bba26"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column(
        "tag",
        "source",
        type_=sa.String(length=50),
        existing_type=sa.Enum(DocumentSource, native_enum=False),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "tag",
        "source",
        type_=sa.Enum(DocumentSource, native_enum=False),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
