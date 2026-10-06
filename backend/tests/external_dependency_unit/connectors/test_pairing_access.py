"""The access-type rules every pairing flow runs: one test per rule."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from ee.onyx.utils import tier
from ee.onyx.utils.tier import Tier
from onyx.configs.constants import DocumentSource
from onyx.connectors import pairing_access
from onyx.connectors.pairing_access import validate_pairing_access
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user

# Any id works: an admin sees every group, and a basic user sees none.
_GROUP_ID = 1


@pytest.fixture
def admin(db_session: Session) -> User:
    return create_test_user(db_session, "pairing_access_admin", is_admin=True)


@pytest.fixture
def basic_user(db_session: Session) -> User:
    return create_test_user(db_session, "pairing_access_basic")


@pytest.fixture
def group_restrictions_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[MagicMock, None, None]:
    settings = MagicMock(allow_connector_group_restrictions=True)
    monkeypatch.setattr(pairing_access, "get_security_settings", lambda: settings)
    yield settings


@pytest.fixture
def ee_business_tier(
    enable_ee: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    monkeypatch.setattr(tier, "LICENSE_ENFORCEMENT_ENABLED", True)
    get_tier = MagicMock(return_value=Tier.BUSINESS)
    monkeypatch.setattr(tier, "get_tier", get_tier)
    return get_tier


def _validate(
    db_session: Session,
    user: User,
    access_type: AccessType,
    data_access_group_ids: list[int] | None = None,
    source: DocumentSource = DocumentSource.SLACK,
) -> None:
    validate_pairing_access(
        db_session,
        user=user,
        source=source,
        access_type=access_type,
        data_access_group_ids=data_access_group_ids,
    )


def _error_code(
    db_session: Session,
    user: User,
    access_type: AccessType,
    data_access_group_ids: list[int] | None = None,
    source: DocumentSource = DocumentSource.SLACK,
) -> OnyxErrorCode:
    with pytest.raises(OnyxError) as exc_info:
        _validate(db_session, user, access_type, data_access_group_ids, source)
    return exc_info.value.error_code


@pytest.mark.usefixtures("tenant_context", "ee_business_tier")
def test_restricted_needs_the_workspace_setting(
    db_session: Session, admin: User, group_restrictions_allowed: MagicMock
) -> None:
    group_restrictions_allowed.allow_connector_group_restrictions = False

    assert (
        _error_code(db_session, admin, AccessType.SYNC_RESTRICTED, [_GROUP_ID])
        is OnyxErrorCode.FEATURE_NOT_AVAILABLE
    )


@pytest.mark.usefixtures(
    "tenant_context", "ee_business_tier", "group_restrictions_allowed"
)
def test_restricted_needs_a_data_access_group(db_session: Session, admin: User) -> None:
    assert (
        _error_code(db_session, admin, AccessType.SYNC_RESTRICTED, [])
        is OnyxErrorCode.INVALID_INPUT
    )
    _validate(db_session, admin, AccessType.SYNC_RESTRICTED, [_GROUP_ID])


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("access_type", [AccessType.PUBLIC, AccessType.SYNC])
def test_data_access_groups_need_a_data_access_type(
    db_session: Session, admin: User, access_type: AccessType
) -> None:
    assert (
        _error_code(db_session, admin, access_type, [_GROUP_ID])
        is OnyxErrorCode.INVALID_INPUT
    )


@pytest.mark.usefixtures("tenant_context")
def test_data_access_groups_must_be_visible(
    db_session: Session, admin: User, basic_user: User
) -> None:
    assert (
        _error_code(db_session, basic_user, AccessType.PRIVATE, [_GROUP_ID])
        is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    )
    _validate(db_session, admin, AccessType.PRIVATE, [_GROUP_ID])
    _validate(db_session, basic_user, AccessType.PRIVATE)


@pytest.mark.usefixtures("tenant_context")
def test_sync_needs_the_business_tier(
    db_session: Session, admin: User, ee_business_tier: MagicMock
) -> None:
    ee_business_tier.return_value = Tier.COMMUNITY

    assert (
        _error_code(db_session, admin, AccessType.SYNC)
        is OnyxErrorCode.FEATURE_NOT_AVAILABLE
    )
    # Not perm-synced, so the tier does not apply.
    _validate(db_session, admin, AccessType.PUBLIC)


@pytest.mark.usefixtures("tenant_context", "ee_business_tier")
def test_sync_needs_a_sync_source(db_session: Session, admin: User) -> None:
    assert (
        _error_code(db_session, admin, AccessType.SYNC, source=DocumentSource.WEB)
        is OnyxErrorCode.INVALID_INPUT
    )
    _validate(db_session, admin, AccessType.SYNC)
