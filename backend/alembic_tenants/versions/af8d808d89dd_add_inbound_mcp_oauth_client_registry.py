"""add inbound mcp oauth client registry

Revision ID: af8d808d89dd
Revises: 5e0d2a7c9f41
Create Date: 2026-10-05 09:44:08.440510

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "af8d808d89dd"
down_revision = "5e0d2a7c9f41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_client",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column("client_metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="public",
    )
    op.create_index(
        "ix_mcp_oauth_client_last_used_at",
        "mcp_oauth_client",
        ["last_used_at"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_client", schema="public")
