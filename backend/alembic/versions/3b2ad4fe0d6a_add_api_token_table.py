"""add api_token table

Revision ID: 3b2ad4fe0d6a
Revises: c92b67e56ec4
Create Date: 2026-10-16 03:00:00.000000

Adds the shared ``api_token`` table. Features move their stored API keys into
it, and point to a row by ``api_token_id``, in later revisions.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3b2ad4fe0d6a"
down_revision = "c92b67e56ec4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_token_platform", "api_token", ["platform"])


def downgrade() -> None:
    op.drop_index("ix_api_token_platform", table_name="api_token")
    op.drop_table("api_token")
