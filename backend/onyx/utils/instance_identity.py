"""Persist the Sentry installation identity independently of callhome telemetry."""

import uuid

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.db.encrypted_kv_store import load_encrypted_kv, upsert_encrypted_kv
from onyx.key_value_store.interface import KvKeyNotFoundError, unwrap_str

_CACHED_UUID: str | None = None


def get_or_generate_uuid() -> str:
    global _CACHED_UUID

    if _CACHED_UUID is not None:
        return _CACHED_UUID

    try:
        _CACHED_UUID = unwrap_str(load_encrypted_kv(KV_CUSTOMER_UUID_KEY))
    except KvKeyNotFoundError:
        _CACHED_UUID = str(uuid.uuid4())
        upsert_encrypted_kv(KV_CUSTOMER_UUID_KEY, {"value": _CACHED_UUID})

    return _CACHED_UUID
