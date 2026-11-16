"""apply the run-time skill limit

Add sandbox.skill_omissions: the plugins the run-time skill limit left out of
the content a sandbox got.

Revision ID: ff11c4042c42
Revises: 7c00f53ab75f
Create Date: 2026-11-12 11:19:14.960270

"""

import logging
import time
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "ff11c4042c42"
down_revision = "7c00f53ab75f"
branch_labels = None
depends_on = None

_LOCK_TIMEOUT = "5s"
_ATTEMPTS = 12
_RETRY_DELAY_S = 5
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"


def _is_lock_timeout(error: DBAPIError) -> bool:
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _with_bounded_lock_wait(table_name: str, change: Callable[[], None]) -> None:
    """Run DDL that needs an ACCESS EXCLUSIVE lock on ``table_name``.

    Running API pods hold row locks on ``sandbox`` while they push skills.
    While the DDL waits for its lock, every other query on the table queues
    behind it. A short lock_timeout keeps that stall short. Each attempt runs
    in a savepoint, so a timeout does not abort the migration transaction.
    """
    bind = op.get_bind()
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                change()
            break
        except DBAPIError as e:
            if attempt == _ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "Could not lock `%s` (attempt %s/%s). Retrying in %ss.",
                table_name,
                attempt,
                _ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def upgrade() -> None:
    _with_bounded_lock_wait(
        "sandbox",
        lambda: op.add_column(
            "sandbox",
            sa.Column(
                "skill_omissions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox", "skill_omissions")
