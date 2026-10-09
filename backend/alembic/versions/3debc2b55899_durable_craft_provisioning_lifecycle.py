"""durable craft provisioning lifecycle

Revision ID: 3debc2b55899
Revises: 4662f8c3e038
Create Date: 2026-07-29 16:05:31.324630

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3debc2b55899"
down_revision = "4662f8c3e038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The non-native status enum was sized to its longest member at creation
    # ("active" → VARCHAR(6)); widen for the new INITIALIZING value.
    op.alter_column(
        "build_session",
        "status",
        type_=sa.String(length=12),
        existing_type=sa.String(length=6),
        existing_nullable=False,
    )
    op.add_column(
        "sandbox",
        sa.Column(
            "provisioning_attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "sandbox",
        sa.Column("provisioning_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Port allocation previously had no uniqueness guarantee, so concurrent
    # creates could have reserved the same port. Ports only need to be unique
    # within one user's sandbox (each user has their own pod/container), so
    # scope the constraint per user. Keep the oldest reservation per
    # (user, port) — within a shared pod its dev server won the bind; later
    # duplicates never served. A cleared session gets a fresh port on its
    # next sleep/restore cycle.
    op.execute(
        """
        UPDATE build_session SET nextjs_port = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id, nextjs_port ORDER BY created_at ASC
                ) AS rn
                FROM build_session
                WHERE nextjs_port IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )
    op.create_index(
        "uq_build_session_nextjs_port",
        "build_session",
        ["user_id", "nextjs_port"],
        unique=True,
        postgresql_where=sa.text("nextjs_port IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_build_session_nextjs_port", table_name="build_session")
    op.drop_column("sandbox", "provisioning_started_at")
    op.drop_column("sandbox", "provisioning_attempt_number")
    # Fold the statuses this revision introduced back into the old set before
    # shrinking the column (non-native enums persist member NAMES).
    op.execute(
        "UPDATE build_session SET status = 'IDLE' "
        "WHERE status IN ('INITIALIZING', 'FAILED')"
    )
    op.alter_column(
        "build_session",
        "status",
        type_=sa.String(length=6),
        existing_type=sa.String(length=12),
        existing_nullable=False,
    )
