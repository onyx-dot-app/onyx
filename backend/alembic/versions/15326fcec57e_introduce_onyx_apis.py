"""Introduce Onyx APIs

Revision ID: 15326fcec57e
Revises: 77d07dffae64
Create Date: 2023-11-11 20:51:24.228999

"""

from alembic import op
import sqlalchemy as sa

from onyx.configs.constants import DocumentSource

# revision identifiers, used by Alembic.
revision = "15326fcec57e"
down_revision = "77d07dffae64"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column("credential", "is_admin", new_column_name="admin_public")
    op.add_column(
        "document",
        sa.Column("from_ingestion_api", sa.Boolean(), nullable=True),
    )
    op.alter_column(
        "connector",
        "source",
        type_=sa.String(length=50),
        existing_type=sa.Enum(DocumentSource, native_enum=False),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.drop_column("document", "from_ingestion_api")
    op.alter_column("credential", "admin_public", new_column_name="is_admin")
