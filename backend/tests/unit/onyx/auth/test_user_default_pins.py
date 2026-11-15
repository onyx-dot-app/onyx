from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.pinned_personas import (
    build_seed_pinned_personas_stmt,
    seed_pinned_personas_from_featured,
)


def _compiled_seed_sql(user_id: UUID) -> str:
    return str(
        build_seed_pinned_personas_stmt(user_id).compile(
            compile_kwargs={"literal_binds": True}
        )
    )


def test_seed_selects_only_featured_public_listed_live_agents() -> None:
    """The reduction of "featured and viewable by this user" at creation time.

    A user has no shares or group memberships the instant their row exists, so
    viewable is exactly public. If someone generalises this to the shared access
    filter, admins start getting other people's private featured agents.
    """
    sql = _compiled_seed_sql(uuid4())

    # Assert the direction of each flag, not just its presence: a filter
    # inverted to `is_(False)` still mentions the column it got wrong.
    assert "persona.is_featured IS true" in sql
    assert "persona.is_public IS true" in sql
    assert "persona.is_listed IS true" in sql
    assert "persona.deleted IS false" in sql
    assert f"persona.id != {DEFAULT_PERSONA_ID}" in sql


def test_seed_orders_by_display_priority_then_id() -> None:
    """Position in the sidebar comes from the admin's ordering, not row order."""
    sql = _compiled_seed_sql(uuid4())

    assert "row_number()" in sql.lower()
    assert "display_priority" in sql
    assert "NULLS LAST" in sql


def test_seed_writes_in_one_statement() -> None:
    """One INSERT ... SELECT, so a user is never half-seeded."""
    sql = _compiled_seed_sql(uuid4())

    assert sql.strip().startswith("INSERT INTO user__pinned_persona")
    assert "SELECT" in sql


@pytest.mark.asyncio
async def test_seeding_commits_on_the_creating_session() -> None:
    """Seeding writes and commits on the session that created the user.

    The commit is not optional: the session context manager the caller opens
    closes without committing, so a flush here would discard every pin.
    """
    user = MagicMock()
    user.id = uuid4()
    db_session = MagicMock(spec=AsyncSession)
    db_session.execute = AsyncMock()
    db_session.commit = AsyncMock()

    await seed_pinned_personas_from_featured(db_session=db_session, user=user)

    db_session.execute.assert_awaited_once()
    db_session.commit.assert_awaited_once()
