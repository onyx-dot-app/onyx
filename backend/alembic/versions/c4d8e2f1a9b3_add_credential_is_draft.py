"""add credential is_draft

Revision ID: c4d8e2f1a9b3
Revises: 47af2651bf8b
Create Date: 2026-10-09 12:00:00.000000

A draft credential is a new account in a connector form, saved before its
connector so checks can run on it. The partial index serves the sweep that
deletes drafts left behind.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c4d8e2f1a9b3"
down_revision = "47af2651bf8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential",
        sa.Column(
            "is_draft",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_credential_draft_time_updated",
        "credential",
        ["time_updated"],
        postgresql_where=sa.text("is_draft"),
    )


def downgrade() -> None:
    op.drop_index("ix_credential_draft_time_updated", table_name="credential")
    op.drop_column("credential", "is_draft")
