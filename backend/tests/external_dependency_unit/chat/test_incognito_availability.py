"""Guards who may start an incognito chat.

The availability rule composes the admin security setting (default off) with
group membership under groups-only mode. Runs against real Postgres because
the membership query is a real join, and a mocked session would return
whatever it is told.
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.incognito import incognito_allowed_for_user
from onyx.db.models import User, User__UserGroup, UserGroup
from onyx.server.security.models import IncognitoAvailability
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "incognito-avail")
    yield user
    db_session.rollback()
    db_session.query(User__UserGroup).filter(
        User__UserGroup.user_id == user.id
    ).delete()
    db_session.query(UserGroup).filter(UserGroup.name.like("incognito-avail-%")).delete(
        synchronize_session=False
    )
    db_session.delete(user)
    db_session.commit()


def _make_group(
    db_session: Session, name: str, user: User, incognito_enabled: bool
) -> UserGroup:
    group = UserGroup(name=name, incognito_enabled=incognito_enabled)
    db_session.add(group)
    db_session.flush()
    db_session.add(User__UserGroup(user_group_id=group.id, user_id=user.id))
    db_session.commit()
    return group


def _availability(mode: IncognitoAvailability) -> MagicMock:
    return MagicMock(incognito_availability=mode)


def test_default_off_refuses_everyone(db_session: Session, owner: User) -> None:
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.OFF),
        ),
    ):
        assert not incognito_allowed_for_user(owner, db_session)


def test_everyone_allows_any_user(db_session: Session, owner: User) -> None:
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.EVERYONE),
        ),
    ):
        assert incognito_allowed_for_user(owner, db_session)


def test_groups_mode_allows_a_member_of_an_enabled_group(
    db_session: Session, owner: User
) -> None:
    _make_group(db_session, "incognito-avail-on", owner, incognito_enabled=True)
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.GROUPS),
        ),
    ):
        assert incognito_allowed_for_user(owner, db_session)


def test_groups_mode_refuses_a_member_of_a_disabled_group(
    db_session: Session, owner: User
) -> None:
    _make_group(db_session, "incognito-avail-off", owner, incognito_enabled=False)
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.GROUPS),
        ),
    ):
        assert not incognito_allowed_for_user(owner, db_session)


def test_groups_mode_refuses_a_user_with_no_groups(
    db_session: Session, owner: User
) -> None:
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.GROUPS),
        ),
    ):
        assert not incognito_allowed_for_user(owner, db_session)


def test_unavailable_store_refuses_even_when_everyone_is_allowed(
    db_session: Session, owner: User
) -> None:
    """The setting cannot grant what the deployment cannot hold."""
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=False),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.EVERYONE),
        ),
    ):
        assert not incognito_allowed_for_user(owner, db_session)


def test_anonymous_user_is_refused_even_when_everyone_is_allowed(
    db_session: Session,
) -> None:
    """Anonymous users share an identity and cannot call teardown."""
    anonymous = MagicMock(is_anonymous=True)
    with (
        patch("onyx.chat.incognito.incognito_context_available", return_value=True),
        patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=_availability(IncognitoAvailability.EVERYONE),
        ),
    ):
        assert not incognito_allowed_for_user(anonymous, db_session)
