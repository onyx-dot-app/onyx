"""personalization_user_info

Revision ID: c8a93a2af083
Revises: 6f4f86aef280
Create Date: 2025-10-14 15:59:03.577343

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c8a93a2af083"
down_revision = "6f4f86aef280"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("personal_name", sa.String(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("personal_role", sa.String(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "use_memories",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.create_table(
        "memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_memory_user_id", "memory", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_user_id", table_name="memory")
    op.drop_table("memory")

    op.drop_column("user", "use_memories")
    op.drop_column("user", "personal_role")
    op.drop_column("user", "personal_name")
