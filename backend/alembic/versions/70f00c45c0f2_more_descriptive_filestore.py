"""More Descriptive Filestore

Revision ID: 70f00c45c0f2
Revises: 3879338f8ba1
Create Date: 2024-05-17 17:51:41.926893

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "70f00c45c0f2"
down_revision = "3879338f8ba1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("file_store", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column(
        "file_store",
        sa.Column(
            "file_origin",
            sa.String(),
            nullable=False,
            server_default="connector",  # Default to connector
        ),
    )
    op.add_column(
        "file_store",
        sa.Column(
            "file_type", sa.String(), nullable=False, server_default="text/plain"
        ),
    )
    op.add_column(
        "file_store",
        sa.Column(
            "file_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE file_store
        SET file_origin = CASE
            WHEN file_name LIKE 'chat__%' THEN 'chat_upload'
            ELSE 'connector'
        END,
        file_name = CASE
            WHEN file_name LIKE 'chat__%' THEN SUBSTR(file_name, 7)
            ELSE file_name
        END,
        file_type = CASE
            WHEN file_name LIKE 'chat__%' THEN 'image/png'
            ELSE 'text/plain'
        END
    """
    )


def downgrade() -> None:
    op.drop_column("file_store", "file_metadata")
    op.drop_column("file_store", "file_type")
    op.drop_column("file_store", "file_origin")
    op.drop_column("file_store", "display_name")
