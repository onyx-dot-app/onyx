"""The secrets an event source's callbacks are given.

One reader, so the webhook server and the drain cannot disagree about which
values a source sees.
"""

from collections.abc import Mapping

from onyx.db.models import ConnectorCredentialPair


def pair_secrets(pair: ConnectorCredentialPair) -> Mapping[str, str]:
    """The pair's decrypted credential JSON. String values only: a source
    reads named secrets, and could not use a nested or numeric one."""
    credential_json = pair.credential.credential_json
    if credential_json is None:
        return {}
    values = credential_json.get_value(apply_mask=False)
    return {key: value for key, value in values.items() if isinstance(value, str)}
