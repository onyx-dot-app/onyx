"""apply the run-time skill limit

Drop uq_skill_automatic_name: the run-time name order now decides which of
two same-name skills a user gets. Add sandbox.skill_omissions: the plugins the
run-time skill limit left out of the content a sandbox got.

Revision ID: ff11c4042c42
Revises: 414dfccc5e24
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
down_revision = "414dfccc5e24"
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
    # A skill push locks sandbox rows and then reads skills. Lock in the same
    # order, so the two cannot deadlock and skills stay readable while this
    # waits for the sandbox table.
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
    _with_bounded_lock_wait(
        "skill",
        lambda: op.drop_index("uq_skill_automatic_name", table_name="skill"),
    )


def downgrade() -> None:
    op.drop_column("sandbox", "skill_omissions")
    # The legacy column is a mirror; the plugin tables keep the real setting.
    # Keep one automatic row of each name so the index can come back: a
    # Required one first, else the oldest. The others lose their setting in
    # the legacy column, so this downgrade is lossy.
    op.execute(
        """
        UPDATE skill SET installation_policy = 'AVAILABLE'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY name
                    ORDER BY installation_policy = 'REQUIRED' DESC, created_at, id
                ) AS position
                FROM skill
                WHERE installation_policy <> 'AVAILABLE'
            ) AS ranked
            WHERE position > 1
        )
        """
    )
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text("installation_policy <> 'AVAILABLE'"),
    )
