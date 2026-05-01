"""add sandbox_token to build_session

Revision ID: d9f3a2c81b47
Revises: a7c3e2b1d4f8
Create Date: 2026-04-29 12:00:00.000000

"""

import secrets

from alembic import op
import sqlalchemy as sa


revision = "d9f3a2c81b47"
down_revision = "a7c3e2b1d4f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add as nullable to allow backfill, then enforce NOT NULL.
    op.add_column(
        "build_session",
        sa.Column("sandbox_token", sa.String(), nullable=True),
    )

    # Backfill: every existing row gets a freshly generated token. Done in
    # Python (not SQL) because Postgres has no token_urlsafe builtin and we
    # want each row to have its own random value, not a shared one.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM build_session")).fetchall()
    for (row_id,) in rows:
        bind.execute(
            sa.text("UPDATE build_session SET sandbox_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(32), "id": row_id},
        )

    op.alter_column("build_session", "sandbox_token", nullable=False)
    op.create_index(
        "ix_build_session_sandbox_token",
        "build_session",
        ["sandbox_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_build_session_sandbox_token", table_name="build_session")
    op.drop_column("build_session", "sandbox_token")
