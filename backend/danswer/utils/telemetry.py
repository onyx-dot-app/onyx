import threading
import uuid
from enum import Enum
from typing import cast

import requests
from sqlalchemy.orm import Session

from danswer.configs.app_configs import DISABLE_TELEMETRY
from danswer.configs.app_configs import ENTERPRISE_EDITION_ENABLED
from danswer.configs.constants import KV_CUSTOMER_UUID_KEY
from danswer.configs.constants import KV_INSTANCE_DOMAIN_KEY
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.models import User
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError

_DANSWER_TELEMETRY_ENDPOINT = "https://telemetry.danswer.ai/anonymous_telemetry"
_CACHED_UUID: str | None = None
_CACHED_INSTANCE_DOMAIN: str | None = None


class RecordType(str, Enum):
    VERSION = "version"
    SIGN_UP = "sign_up"
    USAGE = "usage"
    LATENCY = "latency"
    FAILURE = "failure"


def get_or_generate_uuid() -> str:
    global _CACHED_UUID

    if _CACHED_UUID is not None:
        return _CACHED_UUID

    kv_store = get_kv_store()

    try:
        _CACHED_UUID = cast(str, kv_store.load(KV_CUSTOMER_UUID_KEY))
    except KvKeyNotFoundError:
        _CACHED_UUID = str(uuid.uuid4())
        kv_store.store(KV_CUSTOMER_UUID_KEY, _CACHED_UUID, encrypt=True)

    return _CACHED_UUID


def _get_or_generate_instance_domain() -> str | None:
    global _CACHED_INSTANCE_DOMAIN

    if _CACHED_INSTANCE_DOMAIN is not None:
        return _CACHED_INSTANCE_DOMAIN

    kv_store = get_kv_store()

    try:
        _CACHED_INSTANCE_DOMAIN = cast(str, kv_store.load(KV_INSTANCE_DOMAIN_KEY))
    except KvKeyNotFoundError:
        with Session(get_sqlalchemy_engine()) as db_session:
            first_user = db_session.query(User).first()
            if first_user:
                _CACHED_INSTANCE_DOMAIN = first_user.email.split("@")[-1]
                kv_store.store(
                    KV_INSTANCE_DOMAIN_KEY, _CACHED_INSTANCE_DOMAIN, encrypt=True
                )

    return _CACHED_INSTANCE_DOMAIN


def optional_telemetry(
    record_type: RecordType, data: dict, user_id: str | None = None
) -> None:
    if DISABLE_TELEMETRY:
        return

    try:

        def telemetry_logic() -> None:
            try:
                customer_uuid = get_or_generate_uuid()
                payload = {
                    "data": data,
                    "record": record_type,
                    # If None then it's a flow that doesn't include a user
                    # For cases where the User itself is None, a string is provided instead
                    "user_id": user_id,
                    "customer_uuid": customer_uuid,
                }
                if ENTERPRISE_EDITION_ENABLED:
                    payload["instance_domain"] = _get_or_generate_instance_domain()
                requests.post(
                    _DANSWER_TELEMETRY_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
            except Exception:
                # This way it silences all thread level logging as well
                pass

        # Run in separate thread to have minimal overhead in main flows
        thread = threading.Thread(target=telemetry_logic, daemon=True)
        thread.start()
    except Exception:
        # Should never interfere with normal functions of Danswer
        pass
