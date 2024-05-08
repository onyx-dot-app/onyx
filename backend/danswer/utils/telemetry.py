import threading
import uuid
from enum import Enum
from typing import cast

import requests

from danswer.configs.app_configs import DISABLE_TELEMETRY
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError

CUSTOMER_UUID_KEY = "customer_uuid"
DANSWER_TELEMETRY_ENDPOINT = "https://telemetry.danswer.ai/anonymous_telemetry"


class RecordType(str, Enum):
    VERSION = "version"
    SIGN_UP = "sign_up"
    USAGE = "usage"
    LATENCY = "latency"
    FAILURE = "failure"


def get_or_generate_uuid() -> str:
    kv_store = get_dynamic_config_store()
    try:
        return cast(str, kv_store.load(CUSTOMER_UUID_KEY))
    except ConfigNotFoundError:
        customer_id = str(uuid.uuid4())
        kv_store.store(CUSTOMER_UUID_KEY, customer_id, encrypt=True)
        return customer_id


def optional_telemetry(
    record_type: RecordType, data: dict, user_id: str | None = None
) -> None:
    if DISABLE_TELEMETRY:
        return

    try:

        def telemetry_logic() -> None:
            try:
                payload = {
                    "data": data,
                    "record": record_type,
                    # If None then it's a flow that doesn't include a user
                    # For cases where the User itself is None, a string is provided instead
                    "user_id": user_id,
                    "customer_uuid": get_or_generate_uuid(),
                }
                requests.post(
                    DANSWER_TELEMETRY_ENDPOINT,
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
