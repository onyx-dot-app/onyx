"""backfill write chat for limited service accounts

LIMITED service-account keys created before insert_api_key granted them
write:chat directly (#11763) have an empty effective_permissions column,
which locks them out of the scoped chat APIs. Backfill the grant
(write:chat implies read:chat at read time).

Revision ID: 20f09b642ed0
Revises: 2e0b2b146de1
Create Date: 2026-07-07 09:46:01.019413

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20f09b642ed0"
down_revision = "2e0b2b146de1"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None

user_table = sa.table(
    "user",
    sa.column("role", sa.String),
    sa.column("account_type", sa.String),
    sa.column("effective_permissions", postgresql.JSONB),
)

WRITE_CHAT_PERMS = ["write:chat"]


def upgrade() -> None:
    op.execute(
        user_table.update()
        .where(
            user_table.c.account_type == "SERVICE_ACCOUNT",
            user_table.c.role == "LIMITED",
            user_table.c.effective_permissions == sa.cast([], postgresql.JSONB),
        )
        .values(effective_permissions=WRITE_CHAT_PERMS)
    )


def downgrade() -> None:
    # No-op: backfilled rows are indistinguishable from keys the API-key
    # code granted write:chat after this migration, and clearing those
    # would break them. Leaving the grant in place is harmless.
    pass
