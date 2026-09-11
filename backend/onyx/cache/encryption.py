"""Edition-aware encryption for sensitive cache values."""

import base64
import json

from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes


class CacheValueCodec:
    """Reuse Onyx encryption and record the tenant, purpose, and logical key.

    CE values are not encrypted. EE uses the existing configured encryption key.
    Context checks reject misplaced values; they are not authenticated encryption.
    Backend-specific transactions can encode values without splitting atomic writes.
    """

    def __init__(self, *, tenant_id: str, purpose: str) -> None:
        if not tenant_id or not purpose:
            raise ValueError("Sensitive cache values require a tenant and purpose")
        self._context = [1, tenant_id, purpose]

    def encode(self, key: str, value: bytes) -> bytes:
        envelope = json.dumps(
            [*self._context, key, base64.b64encode(value).decode("ascii")],
            separators=(",", ":"),
        )
        # Explicit key preserves edition dispatch but disables EE legacy-read fallback.
        return encrypt_string_to_bytes(envelope, key=ENCRYPTION_KEY_SECRET)

    def decode(self, key: str, value: bytes) -> bytes:
        try:
            envelope = json.loads(
                decrypt_bytes_to_string(value, key=ENCRYPTION_KEY_SECRET)
            )
            if (
                not isinstance(envelope, list)
                or len(envelope) != 5
                or envelope[:4] != [*self._context, key]
                or not isinstance(envelope[4], str)
            ):
                raise ValueError("Invalid cache value context")
            return base64.b64decode(envelope[4], validate=True)
        except (ValueError, TypeError):
            # Decoding and validation failures must not expose credential values.
            raise ValueError("Invalid sensitive cache value") from None


class EncryptedCache:
    """Opt-in bytes-only view over CacheBackend; encryption follows CE/EE policy.

    Writes require a positive TTL. Keys and TTLs remain visible to the backend.
    Locks, lists, and value comparisons are deliberately outside this interface:
    randomized encryption does not preserve plaintext equality.
    """

    def __init__(self, backend: CacheBackend, codec: CacheValueCodec) -> None:
        self._backend = backend
        self._codec = codec

    def get(self, key: str) -> bytes | None:
        value = self._backend.get(key)
        return None if value is None else self._codec.decode(key, value)

    def getdel(self, key: str) -> bytes | None:
        """Consume atomically; an invalid envelope is removed and raises an error."""
        value = self._backend.getdel(key)
        return None if value is None else self._codec.decode(key, value)

    def set(self, key: str, value: bytes, *, ex: int) -> None:
        if ex <= 0:
            raise ValueError("Encrypted cache writes require a positive TTL")
        self._backend.set(key, self._codec.encode(key, value), ex=ex)

    def set_if_absent(self, key: str, value: bytes, *, ex: int) -> bool:
        if ex <= 0:
            raise ValueError("Encrypted cache writes require a positive TTL")
        return self._backend.set_if_absent(key, self._codec.encode(key, value), ex=ex)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def ttl(self, key: str) -> int:
        return self._backend.ttl(key)
