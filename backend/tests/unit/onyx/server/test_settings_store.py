import pytest

from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings import store as settings_store


class _FakeKvStore:
    def load(self, _key: str) -> dict:
        raise KvKeyNotFoundError()


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
