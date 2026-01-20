"""create_snapshot_table

Revision ID: df6cbd9a37cc
Revises: a441232d9c5a
Create Date: 2026-01-19 14:48:00.757530

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "df6cbd9a37cc"
down_revision = "a441232d9c5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create snapshot table (no enum needed)
    op.create_table(
        "snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index for snapshot
    op.create_index(
        "ix_snapshot_session_created",
        "snapshot",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_snapshot_session_created", table_name="snapshot")

    # Drop table
    op.drop_table("snapshot")
