"""add_hook_and_hook_execution_log_tables

Revision ID: 689433b0d8de
Revises: 93a2e195e25c
Create Date: 2026-03-13 11:25:06.547474

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


# revision identifiers, used by Alembic.
revision = "689433b0d8de"
down_revision = "93a2e195e25c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hook",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "hook_point",
            sa.Enum("document_ingestion", "query_processing", native_enum=False),
            nullable=False,
        ),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        sa.Column("is_reachable", sa.Boolean(), nullable=True),
        sa.Column(
            "fail_strategy",
            sa.Enum("hard", "soft", native_enum=False),
            nullable=False,
            server_default="hard",
        ),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="30.0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("creator_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hook_one_active_per_point",
        "hook",
        ["hook_point"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND deleted = false"),
    )

    op.create_table(
        "hook_execution_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hook_id", sa.Integer(), nullable=False),
        sa.Column(
            "hook_point",
            sa.Enum("document_ingestion", "query_processing", native_enum=False),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hook_id"], ["hook.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hook_execution_log_hook_id", "hook_execution_log", ["hook_id"])
    op.create_index(
        "ix_hook_execution_log_created_at", "hook_execution_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_hook_execution_log_created_at", table_name="hook_execution_log")
    op.drop_index("ix_hook_execution_log_hook_id", table_name="hook_execution_log")
    op.drop_table("hook_execution_log")

    op.drop_index("ix_hook_one_active_per_point", table_name="hook")
    op.drop_table("hook")
