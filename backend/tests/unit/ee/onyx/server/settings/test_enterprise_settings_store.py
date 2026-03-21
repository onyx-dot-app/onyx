import pytest

from ee.onyx.server.enterprise_settings import store as enterprise_settings_store
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.key_value_store.interface import KvKeyNotFoundError


class _FakeKvStore:
    def __init__(self, values: dict[str, dict] | None = None) -> None:
        self._values = values or {}
        self.stored_values: list[tuple[str, dict | None]] = []

    def load(self, key: str) -> dict:
        if key not in self._values:
            raise KvKeyNotFoundError()

        return self._values[key]

    def store(self, key: str, value: dict | None) -> None:
        self.stored_values.append((key, value))
        self._values[key] = value or {}


def test_load_runtime_settings_applies_default_application_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enterprise_settings_store, "get_kv_store", lambda: _FakeKvStore()
    )

    settings = enterprise_settings_store.load_runtime_settings()

    assert settings.application_name == ONYX_DEFAULT_APPLICATION_NAME


def test_load_settings_migrates_legacy_enterprise_settings_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kv_store = _FakeKvStore(
        {
            enterprise_settings_store.LEGACY_KV_ENTERPRISE_SETTINGS_KEY: {
                "application_name": "ACTIVA Enterprise"
            }
        }
    )

    monkeypatch.setattr(
        enterprise_settings_store, "get_kv_store", lambda: kv_store
    )

    settings = enterprise_settings_store.load_settings()

    assert settings.application_name == "ACTIVA Enterprise"
    assert kv_store.stored_values == [
        (
            enterprise_settings_store.KV_ENTERPRISE_SETTINGS_KEY,
            {"application_name": "ACTIVA Enterprise"},
        )
    ]
