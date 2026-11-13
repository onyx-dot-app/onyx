"""The secrets an event source's callbacks get. One reader, so the webhook
server and the drain cannot disagree."""

import json
from collections.abc import Mapping

from onyx.db.models import ConnectorCredentialPair


def pair_secrets(pair: ConnectorCredentialPair) -> Mapping[str, str]:
    """The pair's decrypted credential JSON. A value that is not a string is
    passed as its JSON text; a null is left out, so a missing secret stays
    missing."""
    credential_json = pair.credential.credential_json
    if credential_json is None:
        return {}
    values = credential_json.get_value(apply_mask=False)
    return {
        key: value if isinstance(value, str) else json.dumps(value)
        for key, value in values.items()
        if value is not None
    }
