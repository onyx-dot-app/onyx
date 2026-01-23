"""snapshot_use_sandbox_id_foreign_key

Revision ID: 111d7192d457
Revises: 0ab5805121ef
Create Date: 2026-01-22 16:21:41.711611

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "111d7192d457"
down_revision = "0ab5805121ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sandbox_id column (nullable initially for data migration)
    op.add_column(
        "snapshot",
        sa.Column(
            "sandbox_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Populate sandbox_id from sandbox table via session_id
    op.execute(
        """
        UPDATE snapshot
        SET sandbox_id = sandbox.id
        FROM sandbox
        WHERE snapshot.session_id = sandbox.session_id
        """
    )

    # Make sandbox_id not nullable
    op.alter_column("snapshot", "sandbox_id", nullable=False)

    # Add foreign key constraint for sandbox_id
    op.create_foreign_key(
        "snapshot_sandbox_id_fkey",
        "snapshot",
        "sandbox",
        ["sandbox_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop the old index that used session_id
    op.drop_index("ix_snapshot_session_created", table_name="snapshot")

    # Drop the foreign key constraint on session_id
    op.drop_constraint("snapshot_session_id_fkey", "snapshot", type_="foreignkey")

    # Drop the session_id column
    op.drop_column("snapshot", "session_id")

    # Create new index using sandbox_id
    op.create_index(
        "ix_snapshot_sandbox_created",
        "snapshot",
        ["sandbox_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Drop the new index
    op.drop_index("ix_snapshot_sandbox_created", table_name="snapshot")

    # Add session_id column back (nullable initially for data migration)
    op.add_column(
        "snapshot",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Populate session_id from sandbox table
    op.execute(
        """
        UPDATE snapshot
        SET session_id = sandbox.session_id
        FROM sandbox
        WHERE snapshot.sandbox_id = sandbox.id
        """
    )

    # Make session_id not nullable
    op.alter_column("snapshot", "session_id", nullable=False)

    # Add foreign key constraint for session_id
    op.create_foreign_key(
        "snapshot_session_id_fkey",
        "snapshot",
        "build_session",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Recreate the old index
    op.create_index(
        "ix_snapshot_session_created",
        "snapshot",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )

    # Drop the foreign key constraint on sandbox_id
    op.drop_constraint("snapshot_sandbox_id_fkey", "snapshot", type_="foreignkey")

    # Drop the sandbox_id column
    op.drop_column("snapshot", "sandbox_id")
