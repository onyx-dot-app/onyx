from collections.abc import Mapping

from pydantic import BaseModel

from onyx.configs.constants import KV_LINEAR_APP_CRED_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError


class LinearAppCredentials(BaseModel):
    client_id: str
    client_secret: str


def get_linear_app_cred() -> LinearAppCredentials:
    kv = get_kv_store()
    try:
        raw = kv.load(KV_LINEAR_APP_CRED_KEY)
    except KvKeyNotFoundError as exc:
        raise ValueError("Linear app credential is not configured.") from exc

    if isinstance(raw, str):
        return LinearAppCredentials.model_validate_json(raw)
    if isinstance(raw, Mapping):
        # mypy: convert Mapping[str, JSON_ro] -> dict[str, Any]
        return LinearAppCredentials.model_validate(dict(raw))  # type: ignore[arg-type]

    # Unexpected storage format
    raise ValueError("Invalid Linear app credential format in KV store")


def upsert_linear_app_cred(creds: LinearAppCredentials) -> None:
    # Store as structured JSON (dict) to satisfy KeyValueStore JSON_ro typing
    get_kv_store().store(KV_LINEAR_APP_CRED_KEY, creds.model_dump(), encrypt=True)


def delete_linear_app_cred() -> None:
    get_kv_store().delete(KV_LINEAR_APP_CRED_KEY)
