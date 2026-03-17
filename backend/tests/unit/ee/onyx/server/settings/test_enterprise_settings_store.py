import pytest

from ee.onyx.server.enterprise_settings import store as enterprise_settings_store
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.key_value_store.interface import KvKeyNotFoundError


class _FakeKvStore:
    def load(self, _key: str) -> dict:
        raise KvKeyNotFoundError()

    def store(self, _key: str, _value: dict) -> None:
        return None


def test_load_runtime_settings_applies_default_application_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enterprise_settings_store, "get_kv_store", lambda: _FakeKvStore()
    )

    settings = enterprise_settings_store.load_runtime_settings()

    assert settings.application_name == ONYX_DEFAULT_APPLICATION_NAME
