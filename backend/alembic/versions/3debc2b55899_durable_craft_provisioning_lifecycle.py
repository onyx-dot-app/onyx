"""durable craft provisioning lifecycle

Revision ID: 3debc2b55899
Revises: 0d9c7b6a5e4f
Create Date: 2026-07-29 16:05:31.324630

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3debc2b55899"
down_revision = "0d9c7b6a5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox",
        sa.Column(
            "provisioning_generation",
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
    # creates could have reserved the same port. Keep the newest reservation
    # per port; ports are re-allocated on restore, so nulling is safe.
    op.execute(
        """
        UPDATE build_session SET nextjs_port = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY nextjs_port ORDER BY created_at DESC
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
        ["nextjs_port"],
        unique=True,
        postgresql_where=sa.text("nextjs_port IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_build_session_nextjs_port", table_name="build_session")
    op.drop_column("sandbox", "provisioning_started_at")
    op.drop_column("sandbox", "provisioning_generation")
