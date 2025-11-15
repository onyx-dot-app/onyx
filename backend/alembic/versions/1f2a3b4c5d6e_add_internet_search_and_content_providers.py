"""add internet search and content provider tables

Revision ID: 1f2a3b4c5d6e
Revises: 5e1c073d48a3
Create Date: 2025-11-10 19:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1f2a3b4c5d6e"
down_revision = "5e1c073d48a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internet_search_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_internet_search_provider_is_active",
        "internet_search_provider",
        ["is_active"],
    )

    op.create_table(
        "internet_content_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_internet_content_provider_is_active",
        "internet_content_provider",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_internet_content_provider_is_active", table_name="internet_content_provider"
    )
    op.drop_table("internet_content_provider")
    op.drop_index(
        "ix_internet_search_provider_is_active", table_name="internet_search_provider"
    )
    op.drop_table("internet_search_provider")
