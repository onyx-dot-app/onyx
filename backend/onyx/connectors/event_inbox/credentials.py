"""The secrets an event source's callbacks are given.

One reader, because more than one part of the pipeline needs them: the
drain, to fetch a body a provider only linked to, and later the webhook
server, to verify a delivery. Two readers could disagree about which values
a source sees.
"""

from collections.abc import Mapping

from onyx.db.models import ConnectorCredentialPair


def pair_secrets(pair: ConnectorCredentialPair) -> Mapping[str, str]:
    """The pair's decrypted credential JSON, string values only.

    A source reads named secrets, so a nested or numeric value would only
    reach it as something it cannot use.
    """
    credential_json = pair.credential.credential_json
    if credential_json is None:
        return {}
    values = credential_json.get_value(apply_mask=False)
    return {key: value for key, value in values.items() if isinstance(value, str)}
