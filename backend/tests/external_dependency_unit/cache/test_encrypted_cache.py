"""Sensitive cache values use existing CE/EE encryption on either backend."""

import base64
import json
from collections.abc import Generator
from uuid import uuid4

import pytest

from onyx.cache.encryption import CacheValueCodec, EncryptedCache
from onyx.cache.interface import CacheBackend
from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

TEST_KEY = "cache-test-encryption-key-32bytes!"


@pytest.fixture(params=["ce", "ee", "ee_without_key"])
def edition(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Generator[str, None, None]:
    was_ee = global_version.is_ee_version()
    if request.param == "ce":
        global_version.unset_ee()
    else:
        global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(
        "onyx.cache.encryption.ENCRYPTION_KEY_SECRET",
        "" if request.param == "ee_without_key" else TEST_KEY,
    )
    try:
        yield request.param
    finally:
        if was_ee:
            global_version.set_ee()
        else:
            global_version.unset_ee()
        fetch_versioned_implementation.cache_clear()


def test_cache_roundtrip_and_atomic_operations(
    cache: CacheBackend, edition: str
) -> None:
    key = f"encrypted-cache-test:{uuid4()}"
    codec = CacheValueCodec(tenant_id="public", purpose="test")
    wrapped = EncryptedCache(cache, codec)
    value = b"provider-secret-\x00\xff"
    try:
        assert wrapped.get(key) is None
        assert wrapped.set_if_absent(key, value, ex=60)
        first = cache.get(key)
        assert first is not None
        if edition == "ee":
            assert base64.b64encode(value) not in first
            envelope = json.loads(decrypt_bytes_to_string(first, key=TEST_KEY))
        else:
            # CE stays unencrypted even when an encryption key is configured.
            envelope = json.loads(first)
        assert envelope == [1, "public", "test", key, base64.b64encode(value).decode()]
        assert not wrapped.set_if_absent(key, b"replacement", ex=60)
        assert wrapped.get(key) == value
        assert 0 < wrapped.ttl(key) <= 60
        wrapped.set(key, value, ex=60)
        if edition == "ee":
            assert cache.get(key) != first
        assert wrapped.getdel(key) == value
        assert wrapped.getdel(key) is None
        for ttl in (0, -1):
            with pytest.raises(ValueError, match="positive TTL"):
                wrapped.set(key, value, ex=ttl)
            with pytest.raises(ValueError, match="positive TTL"):
                wrapped.set_if_absent(key, value, ex=ttl)
        assert cache.get(key) is None
    finally:
        wrapped.delete(key)


@pytest.mark.usefixtures("edition")
@pytest.mark.parametrize("mismatch", ["tenant", "purpose", "key", "invalid"])
def test_cache_rejects_misplaced_or_invalid_records(
    cache: CacheBackend, mismatch: str
) -> None:
    key = f"encrypted-cache-test:{uuid4()}"
    codec = CacheValueCodec(tenant_id="public", purpose="test")
    source = CacheValueCodec(
        tenant_id="other" if mismatch == "tenant" else "public",
        purpose="other" if mismatch == "purpose" else "test",
    )
    value = source.encode("other" if mismatch == "key" else key, b"secret-canary")
    if mismatch == "invalid":
        value = b"invalid-secret-canary"
    cache.set(key, value, ex=60)
    try:
        with pytest.raises(
            ValueError, match="^Invalid sensitive cache value$"
        ) as error:
            EncryptedCache(cache, codec).getdel(key)
        assert error.value.__suppress_context__
        assert cache.get(key) is None
    finally:
        cache.delete(key)


@pytest.mark.usefixtures("enable_ee")
def test_ee_does_not_accept_plaintext_or_wrong_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.cache.encryption.ENCRYPTION_KEY_SECRET", TEST_KEY)
    codec = CacheValueCodec(tenant_id="public", purpose="test")
    encrypted = codec.encode("key", b"secret-canary")
    plaintext = decrypt_bytes_to_string(encrypted, key=TEST_KEY).encode()
    with pytest.raises(ValueError, match="^Invalid sensitive cache value$"):
        codec.decode("key", plaintext)
    monkeypatch.setattr(
        "onyx.cache.encryption.ENCRYPTION_KEY_SECRET",
        "another-cache-encryption-test-key",
    )
    with pytest.raises(ValueError, match="^Invalid sensitive cache value$"):
        codec.decode("key", encrypted)
