"""Verify OAuth callback claims against both supported cache backends."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import BaseModel

from onyx.cache.interface import CacheBackend
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import AuthorizationAttemptStore


class _Payload(BaseModel):
    target_id: int


def test_concurrent_callbacks_claim_attempt_once(cache: CacheBackend) -> None:
    store = AuthorizationAttemptStore(
        cache_backend_provider=lambda: cache,
        namespace="oauth-concurrency-test",
        payload_type=_Payload,
    )
    owner_id = str(uuid4())
    attempt = store.store(owner_id=owner_id, payload=_Payload(target_id=7))
    barrier = Barrier(8)

    def claim() -> int | None:
        barrier.wait(timeout=10)
        try:
            return store.consume(
                owner_id=owner_id, state=attempt.state
            ).payload.target_id
        except OnyxError as error:
            if error.detail != "Invalid or expired OAuth authorization attempt":
                raise
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: claim(), range(8)))

    assert results.count(7) == 1
    assert results.count(None) == 7


def test_wrong_owner_cannot_consume_attempt(cache: CacheBackend) -> None:
    store = AuthorizationAttemptStore(
        cache_backend_provider=lambda: cache,
        namespace="oauth-owner-test",
        payload_type=_Payload,
    )
    owner_id = str(uuid4())
    attempt = store.store(owner_id=owner_id, payload=_Payload(target_id=9))
    with pytest.raises(
        OnyxError, match="Invalid or expired OAuth authorization attempt"
    ):
        store.consume(owner_id=str(uuid4()), state=attempt.state)
    assert store.consume(owner_id=owner_id, state=attempt.state).payload.target_id == 9
