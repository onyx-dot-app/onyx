"""User shared sandbox - Phase 1 schema changes

Changes Sandbox from session-owned to user-owned (one sandbox per user),
and changes Snapshot from sandbox-linked to session-linked.

Sandbox table:
- Remove: session_id (unique FK to BuildSession)
- Add: user_id (FK to User, NOT NULL, unique)

Snapshot table:
- Remove: sandbox_id (FK to Sandbox)
- Add: session_id (FK to BuildSession, NOT NULL, ondelete=CASCADE)
- Update index: ix_snapshot_sandbox_created -> ix_snapshot_session_created

Revision ID: 6db00b8237e5
Revises: 111d7192d457
Create Date: 2026-01-23 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6db00b8237e5"
down_revision = "111d7192d457"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # SNAPSHOT: Change from sandbox_id to session_id
    # Must be done BEFORE dropping sandbox.session_id (needed for data migration)
    # ==========================================================================

    # 1. Add session_id column (nullable initially for data migration)
    op.add_column(
        "snapshot",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # 2. Populate session_id from sandbox.session_id via snapshot.sandbox_id
    op.execute(
        """
        UPDATE snapshot
        SET session_id = sandbox.session_id
        FROM sandbox
        WHERE snapshot.sandbox_id = sandbox.id
        """
    )

    # 3. Make session_id not nullable
    op.alter_column("snapshot", "session_id", nullable=False)

    # 4. Add FK constraint for session_id
    op.create_foreign_key(
        "snapshot_session_id_fkey",
        "snapshot",
        "build_session",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 5. Drop old index
    op.drop_index("ix_snapshot_sandbox_created", table_name="snapshot")

    # 6. Drop FK constraint on sandbox_id
    op.drop_constraint("snapshot_sandbox_id_fkey", "snapshot", type_="foreignkey")

    # 7. Drop sandbox_id column
    op.drop_column("snapshot", "sandbox_id")

    # 8. Create new index
    op.create_index(
        "ix_snapshot_session_created",
        "snapshot",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )

    # ==========================================================================
    # SANDBOX: Change from session_id to user_id
    # ==========================================================================

    # 1. Add user_id column (nullable initially for data migration)
    op.add_column(
        "sandbox",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # 2. Populate user_id from build_session.user_id via sandbox.session_id
    op.execute(
        """
        UPDATE sandbox
        SET user_id = build_session.user_id
        FROM build_session
        WHERE sandbox.session_id = build_session.id
        """
    )

    # 3. Delete any sandboxes that couldn't be mapped (orphaned data)
    # This handles sandboxes whose sessions have NULL user_id or were deleted
    op.execute(
        """
        DELETE FROM sandbox WHERE user_id IS NULL
        """
    )

    # 4. Make user_id not nullable
    op.alter_column("sandbox", "user_id", nullable=False)

    # 5. Drop the unique constraint on session_id
    op.drop_constraint("sandbox_session_id_key", "sandbox", type_="unique")

    # 6. Drop FK constraint on session_id
    op.drop_constraint("sandbox_session_id_fkey", "sandbox", type_="foreignkey")

    # 7. Drop session_id column
    op.drop_column("sandbox", "session_id")

    # 8. Add FK constraint for user_id
    op.create_foreign_key(
        "sandbox_user_id_fkey",
        "sandbox",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 9. Add unique constraint on user_id (one sandbox per user)
    op.create_unique_constraint("sandbox_user_id_key", "sandbox", ["user_id"])


def downgrade() -> None:
    # ==========================================================================
    # SANDBOX: Change back from user_id to session_id
    # ==========================================================================

    # 1. Drop unique constraint on user_id
    op.drop_constraint("sandbox_user_id_key", "sandbox", type_="unique")

    # 2. Drop FK constraint on user_id
    op.drop_constraint("sandbox_user_id_fkey", "sandbox", type_="foreignkey")

    # 3. Add session_id column back (nullable initially)
    op.add_column(
        "sandbox",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # 4. NOTE: Cannot reliably restore session_id data since the relationship
    # is now one-to-many (user can have multiple sessions).
    # Set session_id to a random session of the user for data integrity.
    op.execute(
        """
        UPDATE sandbox
        SET session_id = (
            SELECT build_session.id
            FROM build_session
            WHERE build_session.user_id = sandbox.user_id
            ORDER BY build_session.created_at DESC
            LIMIT 1
        )
        """
    )

    # 5. Delete sandboxes that couldn't be mapped
    op.execute(
        """
        DELETE FROM sandbox WHERE session_id IS NULL
        """
    )

    # 6. Make session_id not nullable
    op.alter_column("sandbox", "session_id", nullable=False)

    # 7. Add FK constraint for session_id
    op.create_foreign_key(
        "sandbox_session_id_fkey",
        "sandbox",
        "build_session",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 8. Add unique constraint on session_id
    op.create_unique_constraint("sandbox_session_id_key", "sandbox", ["session_id"])

    # 9. Drop user_id column
    op.drop_column("sandbox", "user_id")

    # ==========================================================================
    # SNAPSHOT: Change back from session_id to sandbox_id
    # ==========================================================================

    # 1. Drop new index
    op.drop_index("ix_snapshot_session_created", table_name="snapshot")

    # 2. Add sandbox_id column back (nullable initially)
    op.add_column(
        "snapshot",
        sa.Column(
            "sandbox_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # 3. Populate sandbox_id from the newly restored sandbox.session_id
    op.execute(
        """
        UPDATE snapshot
        SET sandbox_id = sandbox.id
        FROM sandbox
        WHERE snapshot.session_id = sandbox.session_id
        """
    )

    # 4. Delete snapshots that couldn't be mapped
    op.execute(
        """
        DELETE FROM snapshot WHERE sandbox_id IS NULL
        """
    )

    # 5. Make sandbox_id not nullable
    op.alter_column("snapshot", "sandbox_id", nullable=False)

    # 6. Add FK constraint for sandbox_id
    op.create_foreign_key(
        "snapshot_sandbox_id_fkey",
        "snapshot",
        "sandbox",
        ["sandbox_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 7. Create old index
    op.create_index(
        "ix_snapshot_sandbox_created",
        "snapshot",
        ["sandbox_id", sa.text("created_at DESC")],
        unique=False,
    )

    # 8. Drop FK constraint on session_id
    op.drop_constraint("snapshot_session_id_fkey", "snapshot", type_="foreignkey")

    # 9. Drop session_id column
    op.drop_column("snapshot", "session_id")
