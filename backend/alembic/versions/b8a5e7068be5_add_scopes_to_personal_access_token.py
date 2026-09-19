"""add scopes to personal_access_token

Revision ID: b8a5e7068be5
Revises: 3a9b8d7c6e5f
Create Date: 2026-06-02 10:52:55.752962

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b8a5e7068be5"
down_revision = "3a9b8d7c6e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: existing tokens get NULL = no restriction, so they keep full
    # user access — no behavior change on upgrade.
    op.add_column(
        "personal_access_token",
        sa.Column("scopes", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personal_access_token", "scopes")
