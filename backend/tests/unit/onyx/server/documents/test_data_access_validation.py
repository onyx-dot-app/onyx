"""Gate for creating SYNC_RESTRICTED cc-pairs (ENG-4342)."""

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import _validate_data_access_request
from onyx.server.documents.models import ConnectorCredentialPairMetadata

MODULE = "onyx.server.documents.cc_pair"
DB_SESSION: Any = MagicMock(spec=Session)
USER: Any = MagicMock()


def _metadata(
    access_type: AccessType, restriction_group_ids: list[int]
) -> ConnectorCredentialPairMetadata:
    return ConnectorCredentialPairMetadata(
        name="c",
        access_type=access_type,
        restriction_group_ids=restriction_group_ids,
    )


class _Env:
    def __init__(self) -> None:
        self.toggle_on = True
        self.valid_sync_source = True
        self.existing_group_ids = {1, 2}
        self.tier_check = MagicMock()
        self.scope_check = MagicMock()

    def ee(
        self,
        module: str,
        attr: str,
        noop_return_value: Any,  # noqa: ARG002
    ) -> Callable:
        if attr == "require_business_tier_for_sync_access":
            return self.tier_check
        if attr == "check_if_valid_sync_source":
            return lambda _source: self.valid_sync_source
        raise AssertionError(f"unexpected EE lookup {module}.{attr}")


@pytest.fixture
def env() -> Iterator[_Env]:
    e = _Env()
    with (
        patch(
            f"{MODULE}.get_security_settings",
            side_effect=lambda: SimpleNamespace(
                allow_connector_group_restrictions=e.toggle_on
            ),
        ),
        patch(f"{MODULE}.fetch_ee_implementation_or_noop", side_effect=e.ee),
        patch(
            f"{MODULE}.fetch_connector_by_id",
            return_value=SimpleNamespace(source=DocumentSource.CONFLUENCE),
        ),
        patch(
            f"{MODULE}.fetch_existing_user_group_ids",
            side_effect=lambda _db, ids: set(ids) & e.existing_group_ids,
        ),
        patch(f"{MODULE}.assert_within_scope", e.scope_check),
    ):
        yield e


def _assert_rejected(
    metadata: ConnectorCredentialPairMetadata, code: OnyxErrorCode
) -> None:
    with pytest.raises(OnyxError) as exc:
        _validate_data_access_request(1, metadata, USER, DB_SESSION)
    assert exc.value.error_code == code


def test_accepts_valid_restriction_and_scope_checks_its_groups(env: _Env) -> None:
    _validate_data_access_request(
        1, _metadata(AccessType.SYNC_RESTRICTED, [2, 1]), USER, DB_SESSION
    )
    env.tier_check.assert_called_once_with(AccessType.SYNC_RESTRICTED)
    assert sorted(env.scope_check.call_args.kwargs["requested_group_ids"]) == [1, 2]


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("access_type", [AccessType.SYNC, AccessType.PRIVATE])
def test_rejects_groups_on_other_access_types(access_type: AccessType) -> None:
    _assert_rejected(_metadata(access_type, [1]), OnyxErrorCode.INVALID_INPUT)


def test_other_access_types_without_groups_skip_the_gate(env: _Env) -> None:
    _validate_data_access_request(1, _metadata(AccessType.SYNC, []), USER, DB_SESSION)
    env.tier_check.assert_not_called()
    env.scope_check.assert_not_called()


def test_rejects_when_workspace_toggle_is_off(env: _Env) -> None:
    env.toggle_on = False
    _assert_rejected(
        _metadata(AccessType.SYNC_RESTRICTED, [1]),
        OnyxErrorCode.FEATURE_NOT_AVAILABLE,
    )


def test_rejects_source_without_perm_sync(env: _Env) -> None:
    env.valid_sync_source = False
    _assert_rejected(
        _metadata(AccessType.SYNC_RESTRICTED, [1]), OnyxErrorCode.INVALID_INPUT
    )


@pytest.mark.usefixtures("env")
def test_rejects_restriction_without_groups() -> None:
    _assert_rejected(
        _metadata(AccessType.SYNC_RESTRICTED, []), OnyxErrorCode.INVALID_INPUT
    )


def test_rejects_unknown_group_ids(env: _Env) -> None:
    _assert_rejected(
        _metadata(AccessType.SYNC_RESTRICTED, [1, 99]), OnyxErrorCode.INVALID_INPUT
    )
    env.scope_check.assert_not_called()


def test_perm_synced_covers_both_sync_types() -> None:
    assert AccessType.SYNC.is_perm_synced()
    assert AccessType.SYNC_RESTRICTED.is_perm_synced()
    assert not AccessType.PRIVATE.is_perm_synced()
    assert not AccessType.PUBLIC.is_perm_synced()
