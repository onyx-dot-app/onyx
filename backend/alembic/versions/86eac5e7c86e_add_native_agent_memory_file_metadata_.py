"""add native agent memory file metadata and receipts

Revision ID: 86eac5e7c86e
Revises: ad99acb9be41
Create Date: 2026-09-22 14:56:39.515093

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "86eac5e7c86e"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_call", sa.Column("tool_name", sa.Text(), nullable=True))
    op.drop_column("security_settings", "llm_custom_config_env_injection")
    op.create_table(
        "memory_file_metadata",
        sa.Column(
            "memory_id",
            sa.Integer(),
            sa.ForeignKey("memory.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.UniqueConstraint("user_id", "path"),
    )
    op.create_table(
        "memory_operation_receipt",
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("operation_id", sa.String(256), primary_key=True),
        sa.Column("fingerprint", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("existed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_call", "tool_name")
    op.add_column(
        "security_settings",
        sa.Column("llm_custom_config_env_injection", sa.Boolean(), nullable=True),
    )
    op.drop_table("memory_operation_receipt")
    op.drop_table("memory_file_metadata")
