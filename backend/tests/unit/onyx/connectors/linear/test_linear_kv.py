import json
from typing import Any

import pytest
from pytest_mock import MockerFixture

from onyx.connectors.linear.linear_kv import delete_linear_app_cred
from onyx.connectors.linear.linear_kv import get_linear_app_cred
from onyx.connectors.linear.linear_kv import LinearAppCredentials
from onyx.connectors.linear.linear_kv import upsert_linear_app_cred
from onyx.key_value_store.interface import KvKeyNotFoundError


@pytest.fixture
def fake_kv_store(mocker: MockerFixture) -> Any:
    class FakeKV:
        def __init__(self) -> None:
            self._data: dict[str, Any] = {}

        def store(self, key: str, value: Any, encrypt: bool = False) -> None:
            self._data[key] = value

        def load(self, key: str) -> Any:
            if key not in self._data:
                raise KvKeyNotFoundError(key)
            return self._data[key]

        def delete(self, key: str) -> None:
            self._data.pop(key, None)

    fake_kv = FakeKV()
    mocker.patch("onyx.connectors.linear.linear_kv.get_kv_store", return_value=fake_kv)
    return fake_kv


def test_linear_app_cred_roundtrip(fake_kv_store: Any) -> None:
    creds = LinearAppCredentials(
        client_id="test_client_id", client_secret="test_client_secret"
    )

    # Upsert creds
    upsert_linear_app_cred(creds)

    # Get and verify
    loaded = get_linear_app_cred()
    assert loaded.client_id == "test_client_id"
    assert loaded.client_secret == "test_client_secret"

    # Delete
    delete_linear_app_cred()

    # Verify deleted
    with pytest.raises(ValueError, match="Linear app credential is not configured"):
        get_linear_app_cred()


def test_linear_app_cred_not_configured(fake_kv_store: Any) -> None:
    with pytest.raises(ValueError, match="Linear app credential is not configured"):
        get_linear_app_cred()


def test_linear_app_cred_json_storage(fake_kv_store: Any) -> None:
    creds = LinearAppCredentials(client_id="cid", client_secret="csec")
    upsert_linear_app_cred(creds)

    # Verify stored as JSON
    stored = fake_kv_store.load("linear_app_credential")
    parsed = json.loads(stored) if isinstance(stored, str) else stored
    assert parsed["client_id"] == "cid"
    assert parsed["client_secret"] == "csec"
