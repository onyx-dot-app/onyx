"""add tracing provider config

Revision ID: 7f2a3b9c1d4e
Revises: 8c1d4f6a2e9b
Create Date: 2026-06-29 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "7f2a3b9c1d4e"
down_revision = "8c1d4f6a2e9b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracing_provider_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_type"),
    )


def downgrade() -> None:
    op.drop_table("tracing_provider_config")
