"""The web snapshot of connector-bound fields matches the connector config models.

``connectorBoundFields.json`` lists each source's config fields that are not
credential-bound, the counterpart of ``credentialBoundFields.json``.
"""

import json

from scripts.generate_connector_bound_fields import (
    REGENERATE_COMMAND,
    SNAPSHOT_PATH,
    build_connector_bound_fields,
)


def test_snapshot_matches_connector_config_models() -> None:
    expected = build_connector_bound_fields()
    actual = json.loads(SNAPSHOT_PATH.read_text())
    assert actual == expected, (
        f"{SNAPSHOT_PATH.name} is out of date with the ConnectorConfig "
        f"models. Run `{REGENERATE_COMMAND}`."
    )
