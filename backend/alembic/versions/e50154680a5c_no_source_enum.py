"""No Source Enum

Revision ID: e50154680a5c
Revises: fcd135795f21
Create Date: 2024-03-14 18:06:08.523106

"""

from alembic import op
import sqlalchemy as sa

from onyx.configs.constants import DocumentSource

# revision identifiers, used by Alembic.
revision = "e50154680a5c"
down_revision = "fcd135795f21"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column(
        "search_doc",
        "source_type",
        type_=sa.String(length=50),
        existing_type=sa.Enum(DocumentSource, native_enum=False),
        existing_nullable=False,
    )
    op.execute("DROP TYPE IF EXISTS documentsource")


def downgrade() -> None:
    op.alter_column(
        "search_doc",
        "source_type",
        type_=sa.Enum(DocumentSource, native_enum=False),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
