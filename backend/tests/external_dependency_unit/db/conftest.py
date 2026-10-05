"""Fixtures for testing DAL classes against a real PostgreSQL database.

These fixtures build on the db_session and tenant_context fixtures from
the parent conftest (tests/external_dependency_unit/conftest.py).

Requires a running Postgres instance. Run with::

    python -m dotenv -f .vscode/.env run -- pytest tests/external_dependency_unit/db/
"""

from collections.abc import Callable, Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from onyx.db.models import ScimToken, ScimUserMapping, User, UserGroup
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.shard_test_utils import temporary_database

ScimUserFactory = Callable[[str | None], tuple[User, ScimUserMapping]]


@pytest.fixture
def scim_dal(db_session: Session) -> ScimDAL:
    """A ScimDAL backed by the real test database session."""
    return ScimDAL(db_session)


@pytest.fixture
def scim_user_factory(
    db_session: Session,
) -> Generator[ScimUserFactory, None, None]:
    """Factory for (user, mapping) pairs, cleaned up after the test."""
    created: list[tuple[User, ScimUserMapping]] = []

    def _create(scim_username: str | None) -> tuple[User, ScimUserMapping]:
        user = create_test_user(
            db_session, f"scim_user_{uuid4().hex[:8]}", assign_default_group=False
        )
        mapping = ScimUserMapping(
            external_id=f"ext-{uuid4().hex[:12]}",
            user_id=user.id,
            scim_username=scim_username,
        )
        db_session.add(mapping)
        db_session.flush()
        created.append((user, mapping))
        return user, mapping

    yield _create

    for user, mapping in created:
        db_session.delete(mapping)
        db_session.delete(user)
    db_session.commit()


@pytest.fixture
def scim_token_factory(
    db_session: Session,
) -> Generator[Callable[..., ScimToken], None, None]:
    """Factory that creates ScimToken rows and cleans them up after the test."""
    created_ids: list[int] = []

    def _create(
        name: str = "test-token",
        hashed_token: str | None = None,
        token_display: str = "onyx_scim_****test",
        created_by_id: UUID | None = None,
    ) -> ScimToken:
        token = ScimToken(
            name=name,
            hashed_token=hashed_token or uuid4().hex,
            token_display=token_display,
            created_by_id=created_by_id or uuid4(),
        )
        db_session.add(token)
        db_session.flush()
        created_ids.append(token.id)
        return token

    yield _create

    for token_id in created_ids:
        obj = db_session.get(ScimToken, token_id)
        if obj:
            db_session.delete(obj)
    db_session.commit()


@pytest.fixture
def user_group_factory(
    db_session: Session,
) -> Generator[Callable[..., UserGroup], None, None]:
    """Factory that creates UserGroup rows for testing group mappings."""
    created_ids: list[int] = []

    def _create(name: str | None = None) -> UserGroup:
        group = UserGroup(name=name or f"test-group-{uuid4().hex[:8]}")
        db_session.add(group)
        db_session.flush()
        created_ids.append(group.id)
        return group

    yield _create

    for group_id in created_ids:
        obj = db_session.get(UserGroup, group_id)
        if obj:
            db_session.delete(obj)
    db_session.commit()


@pytest.fixture(scope="module")
def second_database() -> Generator[str, None, None]:
    """A real second database for the shard suites.

    Module-scoped so each suite gets its own, rather than sharing state through a
    database that another module is reconfiguring shards against.
    """
    yield from temporary_database("onyx_shard_test")
