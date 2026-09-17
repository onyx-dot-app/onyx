from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import AuthorizationAttemptStore
from onyx.oauth.models import AuthorizationAttempt
from tests.unit.fakes import FakeCache

_STATE_ONE = "a" * 43
_STATE_TWO = "b" * 43


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: int


class _WrongPayload(BaseModel):
    unexpected: bool


def _store(
    cache: FakeCache, namespace: str = "mcp"
) -> AuthorizationAttemptStore[_Payload]:
    return AuthorizationAttemptStore(
        cache,
        namespace=namespace,
        payload_type=_Payload,
        ttl_seconds=300,
    )


def test_store_generates_isolated_one_time_attempts() -> None:
    cache = FakeCache()
    store = _store(cache)

    first = store.store(owner_id="user-1", payload=_Payload(target_id=1))
    second = store.store(owner_id="user-1", payload=_Payload(target_id=2))

    assert first.state != second.state
    assert set(cache.expiries.values()) == {300}
    assert all(
        key.startswith("oauth:authorization_attempt:v1:mcp:") for key in cache.store
    )
    assert all(
        component not in key
        for key in cache.store
        for component in ("user-1", first.state, second.state)
    )
    assert store.consume(owner_id="user-1", state=second.state) == second
    assert store.consume(owner_id="user-1", state=first.state) == first
    with pytest.raises(OnyxError) as error:
        store.consume(owner_id="user-1", state=first.state)
    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_attempt_is_bound_to_namespace_owner_and_state() -> None:
    cache = FakeCache()
    mcp_store = _store(cache)
    connector_store = _store(cache, namespace="connector")
    attempt = mcp_store.store(
        owner_id="user-1",
        state=_STATE_ONE,
        payload=_Payload(target_id=1),
    )

    for store, owner_id, state in (
        (connector_store, "user-1", attempt.state),
        (mcp_store, "user-2", attempt.state),
        (mcp_store, "user-1", _STATE_TWO),
    ):
        with pytest.raises(OnyxError, match="Invalid or expired"):
            store.consume(owner_id=owner_id, state=state)

    assert mcp_store.consume(owner_id="user-1", state=attempt.state) == attempt


def test_same_state_is_isolated_between_owners() -> None:
    store = _store(FakeCache())
    first = store.store(
        owner_id="user-1",
        state=_STATE_ONE,
        payload=_Payload(target_id=1),
    )
    second = store.store(
        owner_id="user-2",
        state=_STATE_ONE,
        payload=_Payload(target_id=2),
    )

    assert store.consume(owner_id="user-2", state=second.state) == second
    assert store.consume(owner_id="user-1", state=first.state) == first


def test_attempt_supports_unicode_owner_id() -> None:
    store = _store(FakeCache())
    attempt = store.store(owner_id="用户-1", payload=_Payload(target_id=1))

    assert store.consume(owner_id="用户-1", state=attempt.state) == attempt


def test_store_does_not_overwrite_duplicate_state() -> None:
    store = _store(FakeCache())
    first = store.store(
        owner_id="user-1",
        state=_STATE_ONE,
        payload=_Payload(target_id=1),
    )

    with pytest.raises(OnyxError) as error:
        store.store(
            owner_id="user-1",
            state=_STATE_ONE,
            payload=_Payload(target_id=2),
        )

    assert error.value.error_code is OnyxErrorCode.CONFLICT
    assert store.consume(owner_id="user-1", state=_STATE_ONE) == first


def test_consume_rejects_malformed_or_wrong_payload_and_removes_it() -> None:
    cache = FakeCache()
    store = _store(cache)
    store.store(
        owner_id="user-1",
        state=_STATE_ONE,
        payload=_Payload(target_id=1),
    )
    malformed_key = next(iter(cache.store))
    cache.store[malformed_key] = b"not-json"

    store.store(
        owner_id="user-1",
        state=_STATE_TWO,
        payload=_Payload(target_id=1),
    )
    wrong_payload_key = next(key for key in cache.store if key != malformed_key)
    cache.store[wrong_payload_key] = (
        AuthorizationAttempt[_WrongPayload](
            namespace="mcp",
            owner_id="user-1",
            state=_STATE_TWO,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            payload=_WrongPayload(unexpected=True),
        )
        .model_dump_json()
        .encode()
    )

    for state in (_STATE_ONE, _STATE_TWO):
        with pytest.raises(OnyxError, match="Invalid or expired"):
            store.consume(owner_id="user-1", state=state)

    assert malformed_key not in cache.store
    assert wrong_payload_key not in cache.store


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("namespace", "connector"),
        ("owner_id", "user-2"),
        ("state", _STATE_TWO),
    ],
)
def test_consume_rejects_and_removes_tampered_envelope(
    field: str,
    value: str,
) -> None:
    cache = FakeCache()
    store = _store(cache)
    attempt = store.store(
        owner_id="user-1",
        state=_STATE_ONE,
        payload=_Payload(target_id=1),
    )
    key = next(iter(cache.store))
    cache.store[key] = (
        attempt.model_copy(update={field: value}).model_dump_json().encode()
    )

    with pytest.raises(OnyxError, match="Invalid or expired"):
        store.consume(owner_id="user-1", state=_STATE_ONE)
    with pytest.raises(OnyxError, match="Invalid or expired"):
        store.consume(owner_id="user-1", state=_STATE_ONE)


def test_consume_rejects_expired_attempt_after_atomic_removal() -> None:
    cache = FakeCache()
    store = _store(cache)
    attempt = store.store(owner_id="user-1", payload=_Payload(target_id=1))
    key = next(iter(cache.store))
    cache.store[key] = (
        attempt.model_copy(
            update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
        .model_dump_json()
        .encode()
    )

    with pytest.raises(OnyxError, match="Invalid or expired"):
        store.consume(owner_id="user-1", state=attempt.state)
    with pytest.raises(OnyxError, match="Invalid or expired"):
        store.consume(owner_id="user-1", state=attempt.state)


@pytest.mark.parametrize("namespace", ["", "MCP", "mcp:oauth", "-mcp", "x" * 65])
def test_store_rejects_invalid_namespace(namespace: str) -> None:
    with pytest.raises(ValueError, match="namespace"):
        _store(FakeCache(), namespace=namespace)


@pytest.mark.parametrize("ttl_seconds", [0, 601])
def test_store_rejects_out_of_range_ttl(ttl_seconds: int) -> None:
    with pytest.raises(ValueError, match="TTL"):
        AuthorizationAttemptStore(
            FakeCache(),
            namespace="mcp",
            payload_type=_Payload,
            ttl_seconds=ttl_seconds,
        )


@pytest.mark.parametrize("state", ["", "x", "invalid.state.with.dots"])
def test_store_rejects_invalid_caller_state(state: str) -> None:
    with pytest.raises(ValueError):
        _store(FakeCache()).store(
            owner_id="user-1",
            state=state,
            payload=_Payload(target_id=1),
        )
