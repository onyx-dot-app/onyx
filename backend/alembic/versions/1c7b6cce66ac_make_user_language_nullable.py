"""make user language nullable

Revision ID: 1c7b6cce66ac
Revises: e22aca06966a
Create Date: 2026-10-07 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1c7b6cce66ac"
down_revision = "e22aca06966a"
branch_labels = None
depends_on = None

user_table = sa.table("user", sa.column("language", sa.String()))


def upgrade() -> None:
    # NULL = follow the workspace default. An existing "en" row is
    # indistinguishable from a deliberate choice, so it follows the default too.
    op.alter_column("user", "language", nullable=True, server_default=None)
    op.execute(
        sa.update(user_table).where(user_table.c.language == "en").values(language=None)
    )


def downgrade() -> None:
    op.execute(
        sa.update(user_table)
        .where(user_table.c.language.is_(None))
        .values(language="en")
    )
    op.alter_column("user", "language", nullable=False, server_default="en")
