"""add custom_headers to mcp_server

Revision ID: d62183349b1e
Revises: f57f35403f6c
Create Date: 2026-07-28 14:09:39.216317

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d62183349b1e"
down_revision = "f57f35403f6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # EncryptedJson column: encrypted bytes at rest.
    op.add_column(
        "mcp_server",
        sa.Column("custom_headers", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server", "custom_headers")
