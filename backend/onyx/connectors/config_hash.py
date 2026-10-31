import hashlib
import json
from typing import Any


def compute_connector_config_hash(config: dict[str, Any] | None) -> str | None:
    """Returns the sha256 of the canonical connector config JSON.

    Capability reports and index attempts store this hash to tell which config
    they ran with, so every writer must use this function to keep stored hashes
    comparable.
    """
    if config is None:
        return None
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
