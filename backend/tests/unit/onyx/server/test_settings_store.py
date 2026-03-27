import pytest

from onyx.configs.app_configs import DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings import store as settings_store
from onyx.server.settings.models import (
    DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_NO_VECTOR_DB,
)
from onyx.server.settings.models import DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_VECTOR_DB
from onyx.server.settings.models import Settings


class _FakeKvStore:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data

    def load(self, _key: str) -> dict:
        if self._data is None:
            raise KvKeyNotFoundError()
        return self._data


class _FakeCache:
    def __init__(self) -> None:
        self._vals: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._vals.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self._vals[key] = value.encode("utf-8")


def test_load_settings_uses_model_defaults_when_no_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no settings are stored (vector DB enabled), load_settings() should
    resolve the default token threshold to 200."""
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore())
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "DISABLE_VECTOR_DB", False)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB
    assert (
        settings.file_token_count_threshold_k
        == DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_VECTOR_DB
    )


def test_load_settings_uses_high_token_default_when_vector_db_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When vector DB is disabled and no settings are stored, the token
    threshold should default to 10000 (10M tokens)."""
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore())
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "DISABLE_VECTOR_DB", True)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB
    assert (
        settings.file_token_count_threshold_k
        == DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_NO_VECTOR_DB
    )


def test_load_settings_preserves_explicit_value_when_vector_db_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When vector DB is disabled but admin explicitly set a token threshold,
    that value should be preserved (not overridden by the 10000 default)."""
    stored = Settings(file_token_count_threshold_k=500).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "DISABLE_VECTOR_DB", True)

    settings = settings_store.load_settings()

    assert settings.file_token_count_threshold_k == 500


def test_load_settings_preserves_zero_token_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value of 0 means 'no limit' and should be preserved."""
    stored = Settings(file_token_count_threshold_k=0).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "DISABLE_VECTOR_DB", True)

    settings = settings_store.load_settings()

    assert settings.file_token_count_threshold_k == 0


def test_load_settings_resolves_zero_upload_size_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value of 0 should be treated as unset and resolved to the default."""
    stored = Settings(user_file_max_upload_size_mb=0).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB


def test_load_settings_clamps_upload_size_to_env_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the stored upload size exceeds MAX_ALLOWED_UPLOAD_SIZE_MB, it should
    be clamped to the env-configured maximum."""
    stored = Settings(user_file_max_upload_size_mb=500).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "MAX_ALLOWED_UPLOAD_SIZE_MB", 250)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == 250


def test_load_settings_preserves_upload_size_within_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the stored upload size is within MAX_ALLOWED_UPLOAD_SIZE_MB, it should
    be preserved unchanged."""
    stored = Settings(user_file_max_upload_size_mb=150).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "MAX_ALLOWED_UPLOAD_SIZE_MB", 250)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == 150


def test_load_settings_zero_upload_size_resolves_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value of 0 should be treated as unset and resolved to the default,
    clamped to MAX_ALLOWED_UPLOAD_SIZE_MB."""
    stored = Settings(user_file_max_upload_size_mb=0).model_dump()
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore(stored))
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "MAX_ALLOWED_UPLOAD_SIZE_MB", 100)
    monkeypatch.setattr(settings_store, "DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB", 100)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == 100


def test_load_settings_default_clamped_to_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB exceeds MAX_ALLOWED_UPLOAD_SIZE_MB,
    the effective default should be min(DEFAULT, MAX)."""
    monkeypatch.setattr(settings_store, "get_kv_store", lambda: _FakeKvStore())
    monkeypatch.setattr(settings_store, "get_cache_backend", lambda: _FakeCache())
    monkeypatch.setattr(settings_store, "DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB", 100)
    monkeypatch.setattr(settings_store, "MAX_ALLOWED_UPLOAD_SIZE_MB", 50)

    settings = settings_store.load_settings()

    assert settings.user_file_max_upload_size_mb == 50
