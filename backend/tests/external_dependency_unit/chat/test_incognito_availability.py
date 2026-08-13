"""Guards who may start an incognito chat.

The availability rule composes the admin security setting (default off) with
group membership under groups-only mode. Runs against real Postgres because
the membership query is a real join, and a mocked session would return
whatever it is told.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.incognito import incognito_allowed_for_user
from onyx.db.models import User, User__UserGroup, UserGroup
from onyx.server.security.models import IncognitoAvailability
from tests.external_dependency_unit.conftest import create_test_user

GROUP_NAME_PREFIX = "incognito-avail-"


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "incognito-avail")
    yield user
    db_session.rollback()
    db_session.query(User__UserGroup).filter(
        User__UserGroup.user_id == user.id
    ).delete()
    db_session.query(UserGroup).filter(
        UserGroup.name.like(f"{GROUP_NAME_PREFIX}%")
    ).delete(synchronize_session=False)
    db_session.delete(user)
    db_session.commit()


def _make_group(db_session: Session, user: User, incognito_enabled: bool) -> None:
    group = UserGroup(
        name=f"{GROUP_NAME_PREFIX}{incognito_enabled}",
        incognito_enabled=incognito_enabled,
    )
    db_session.add(group)
    db_session.flush()
    db_session.add(User__UserGroup(user_group_id=group.id, user_id=user.id))
    db_session.commit()


@contextmanager
def _workspace(
    mode: IncognitoAvailability, store_available: bool = True
) -> Iterator[None]:
    """Both settings readers return the same mode, so a test that does not care
    which one is used passes either way."""
    settings = MagicMock(incognito_availability=mode)
    with (
        patch(
            "onyx.chat.incognito.incognito_context_available",
            return_value=store_available,
        ),
        patch("onyx.chat.incognito.get_security_settings", return_value=settings),
        patch("onyx.chat.incognito.load_effective_uncached", return_value=settings),
    ):
        yield


@pytest.mark.parametrize(
    "mode,group_enabled,allowed",
    [
        (IncognitoAvailability.OFF, None, False),
        (IncognitoAvailability.EVERYONE, None, True),
        (IncognitoAvailability.GROUPS, True, True),
        (IncognitoAvailability.GROUPS, False, False),
        # No group at all, which is the case a membership join can get wrong.
        (IncognitoAvailability.GROUPS, None, False),
    ],
)
def test_availability_setting_decides(
    db_session: Session,
    owner: User,
    mode: IncognitoAvailability,
    group_enabled: bool | None,
    allowed: bool,
) -> None:
    if group_enabled is not None:
        _make_group(db_session, owner, group_enabled)

    with _workspace(mode):
        assert incognito_allowed_for_user(owner, db_session) is allowed


def test_unavailable_store_refuses_what_the_setting_allows(
    db_session: Session, owner: User
) -> None:
    """The setting cannot grant what the deployment cannot hold."""
    with _workspace(IncognitoAvailability.EVERYONE, store_available=False):
        assert not incognito_allowed_for_user(owner, db_session)


def test_anonymous_user_is_refused(db_session: Session) -> None:
    """Anonymous users share an identity and cannot call teardown."""
    anonymous = MagicMock(is_anonymous=True)
    with _workspace(IncognitoAvailability.EVERYONE):
        assert not incognito_allowed_for_user(anonymous, db_session)


def test_enforcement_reads_past_the_settings_cache(
    db_session: Session, owner: User
) -> None:
    """Cache invalidation is process-local, so a second api_server would keep
    authorizing against a revoked setting for the cache TTL."""
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=MagicMock(
                incognito_availability=IncognitoAvailability.EVERYONE
            ),
        ),
        patch(
            "onyx.chat.incognito.load_effective_uncached",
            return_value=MagicMock(incognito_availability=IncognitoAvailability.OFF),
        ),
    ):
        assert incognito_allowed_for_user(owner, db_session)
        assert not incognito_allowed_for_user(owner, db_session, cached=False)
