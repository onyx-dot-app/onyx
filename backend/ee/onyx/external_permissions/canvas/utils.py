from typing import Any

from onyx.db.models import ConnectorCredentialPair


def credential_json(cc_pair: ConnectorCredentialPair) -> dict[str, Any]:
    return (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
