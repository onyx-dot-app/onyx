import pytest

from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings import store as settings_store


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


class _FakeCache:
    def __init__(self) -> None:
        self._vals: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._vals.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self._vals[key] = value.encode("utf-8")


def test_load_settings_includes_user_file_max_upload_size_mb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore())
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "USER_FILE_MAX_UPLOAD_SIZE_MB", 77)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == 77


def test_load_settings_migrates_legacy_settings_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kv_store = _FakeKvStore(
        {settings_store.LEGACY_KV_SETTINGS_KEY: {"gpu_enabled": True}}
    )

    monkeypatch.setattr(settings_store, "get_kv_store", lambda: kv_store)
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())

    settings = settings_store.load_settings()

    assert settings.gpu_enabled is True
    assert kv_store.stored_values == [
        (settings_store.KV_SETTINGS_KEY, {"gpu_enabled": True})
    ]
