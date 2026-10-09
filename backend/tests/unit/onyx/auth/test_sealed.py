import base64
from datetime import timedelta
from uuid import uuid4

import pytest

from onyx.auth import sealed
from onyx.auth.sealed import seal_draft_credential, unseal_draft_credential
from onyx.configs.constants import DocumentSource
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_JSON = {"confluence_access_token": "secret-token", "wiki_base": "https://x"}


def test_round_trip_returns_the_draft() -> None:
    user_id = uuid4()
    token = seal_draft_credential(
        _JSON, user_id=user_id, source=DocumentSource.CONFLUENCE
    )

    draft = unseal_draft_credential(token, user_id=user_id)

    assert draft.credential_json == _JSON
    assert draft.source == DocumentSource.CONFLUENCE
    assert draft.user_id == user_id


def test_sealed_string_does_not_hold_the_secret_in_the_clear() -> None:
    token = seal_draft_credential(
        _JSON, user_id=uuid4(), source=DocumentSource.CONFLUENCE
    )

    assert "secret-token" not in base64.urlsafe_b64decode(token).decode(errors="ignore")


def test_a_changed_byte_is_rejected() -> None:
    user_id = uuid4()
    raw = bytearray(
        base64.urlsafe_b64decode(
            seal_draft_credential(
                _JSON, user_id=user_id, source=DocumentSource.CONFLUENCE
            )
        )
    )
    raw[-1] ^= 1

    with pytest.raises(OnyxError) as error:
        unseal_draft_credential(
            base64.urlsafe_b64encode(bytes(raw)).decode(), user_id=user_id
        )

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_another_users_draft_is_rejected() -> None:
    token = seal_draft_credential(
        _JSON, user_id=uuid4(), source=DocumentSource.CONFLUENCE
    )

    with pytest.raises(OnyxError) as error:
        unseal_draft_credential(token, user_id=uuid4())

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_a_draft_from_another_tenant_is_rejected() -> None:
    user_id = uuid4()
    reset = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
    try:
        token = seal_draft_credential(
            _JSON, user_id=user_id, source=DocumentSource.CONFLUENCE
        )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset)
    reset = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
    try:
        with pytest.raises(OnyxError) as error:
            unseal_draft_credential(token, user_id=user_id)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset)

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_an_expired_draft_is_rejected() -> None:
    user_id = uuid4()
    token = seal_draft_credential(
        _JSON,
        user_id=user_id,
        source=DocumentSource.CONFLUENCE,
        ttl=timedelta(seconds=-1),
    )

    with pytest.raises(OnyxError) as error:
        unseal_draft_credential(token, user_id=user_id)

    assert error.value.error_code == OnyxErrorCode.CREDENTIAL_EXPIRED


def test_a_draft_sealed_with_another_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    token = seal_draft_credential(
        _JSON, user_id=user_id, source=DocumentSource.CONFLUENCE
    )
    monkeypatch.setattr(sealed, "_KEY", sealed._derive_key("another-secret"))

    with pytest.raises(OnyxError) as error:
        unseal_draft_credential(token, user_id=user_id)

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize("garbage", ["", "not base64!", "c2hvcnQ="])
def test_garbage_is_rejected(garbage: str) -> None:
    with pytest.raises(OnyxError) as error:
        unseal_draft_credential(garbage, user_id=uuid4())

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
