"""The web snapshot of credential-bound fields matches the binding models.

The web create form reads ``credentialBoundFields.json`` to show bound fields
above the credential section.
"""

import json

from scripts.generate_credential_bound_fields import (
    REGENERATE_COMMAND,
    SNAPSHOT_PATH,
    build_credential_bound_fields,
)


def test_snapshot_matches_binding_models() -> None:
    expected = build_credential_bound_fields()
    actual = json.loads(SNAPSHOT_PATH.read_text())
    assert actual == expected, (
        f"{SNAPSHOT_PATH.name} is out of date with the CredentialBinding "
        f"models. Run `{REGENERATE_COMMAND}`."
    )
