"""remove voice_provider deleted column

Revision ID: 1d78c0ca7853
Revises: a3f8b2c1d4e5
Create Date: 2026-03-26 11:30:53.883127

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1d78c0ca7853"
down_revision = "a3f8b2c1d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hard-delete any soft-deleted rows before dropping the column
    op.execute("DELETE FROM voice_provider WHERE deleted = true")
    op.drop_column("voice_provider", "deleted")


def downgrade() -> None:
    op.add_column(
        "voice_provider",
        sa.Column(
            "deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
