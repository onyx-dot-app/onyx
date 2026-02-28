"""Unit tests for federated OAuth state generation and verification.

Uses unittest.mock to patch get_cache_backend so no external services
are needed.  Verifies the generate -> verify round-trip, one-time-use
semantics, TTL propagation, and error handling.
"""

from unittest.mock import patch

import pytest

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock
from onyx.federated_connectors.oauth_utils import generate_oauth_state
from onyx.federated_connectors.oauth_utils import OAUTH_STATE_TTL
from onyx.federated_connectors.oauth_utils import OAuthSession
from onyx.federated_connectors.oauth_utils import verify_oauth_state


class _MemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.set_calls: list[dict[str, object]] = []

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self.set_calls.append({"key": key, "ex": ex})
        if isinstance(value, bytes):
            self._store[key] = value
        else:
            self._store[key] = str(value).encode()

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._store

    def expire(self, key: str, seconds: int) -> None:
        pass

    def ttl(self, key: str) -> int:
        return -2 if key not in self._store else -1

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        raise NotImplementedError

    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        raise NotImplementedError


def _patched(cache: _MemoryCacheBackend):  # type: ignore[no-untyped-def]
    return patch(
        "onyx.federated_connectors.oauth_utils.get_cache_backend",
        return_value=cache,
    )


class TestGenerateAndVerifyRoundTrip:
    def test_round_trip_basic(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            state = generate_oauth_state(
                federated_connector_id=42,
                user_id="user-abc",
            )
            session = verify_oauth_state(state)

        assert session.federated_connector_id == 42
        assert session.user_id == "user-abc"
        assert session.redirect_uri is None
        assert session.additional_data == {}

    def test_round_trip_with_all_fields(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            state = generate_oauth_state(
                federated_connector_id=7,
                user_id="user-xyz",
                redirect_uri="https://example.com/callback",
                additional_data={"scope": "read"},
            )
            session = verify_oauth_state(state)

        assert session.federated_connector_id == 7
        assert session.user_id == "user-xyz"
        assert session.redirect_uri == "https://example.com/callback"
        assert session.additional_data == {"scope": "read"}


class TestOneTimeUse:
    def test_verify_deletes_state(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            state = generate_oauth_state(federated_connector_id=1, user_id="u")
            verify_oauth_state(state)

            with pytest.raises(ValueError, match="OAuth state not found"):
                verify_oauth_state(state)


class TestTTLPropagation:
    def test_default_ttl(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            generate_oauth_state(federated_connector_id=1, user_id="u")

        assert len(cache.set_calls) == 1
        assert cache.set_calls[0]["ex"] == OAUTH_STATE_TTL

    def test_custom_ttl(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            generate_oauth_state(federated_connector_id=1, user_id="u", ttl=600)

        assert cache.set_calls[0]["ex"] == 600


class TestVerifyInvalidState:
    def test_missing_state_raises(self) -> None:
        cache = _MemoryCacheBackend()
        with _patched(cache):
            state = generate_oauth_state(federated_connector_id=1, user_id="u")
            # Manually clear the cache to simulate expiration
            cache._store.clear()

            with pytest.raises(ValueError, match="OAuth state not found"):
                verify_oauth_state(state)


class TestOAuthSessionSerialization:
    def test_to_dict_from_dict_round_trip(self) -> None:
        session = OAuthSession(
            federated_connector_id=5,
            user_id="u-123",
            redirect_uri="https://redir.example.com",
            additional_data={"key": "val"},
        )
        d = session.to_dict()
        restored = OAuthSession.from_dict(d)

        assert restored.federated_connector_id == 5
        assert restored.user_id == "u-123"
        assert restored.redirect_uri == "https://redir.example.com"
        assert restored.additional_data == {"key": "val"}

    def test_from_dict_defaults(self) -> None:
        minimal = {"federated_connector_id": 1, "user_id": "u"}
        session = OAuthSession.from_dict(minimal)
        assert session.redirect_uri is None
        assert session.additional_data == {}
