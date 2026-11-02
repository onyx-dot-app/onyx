"""Writes web/src/lib/connectors/credentialBoundFields.json.

The file maps each source whose connector config has a ``CredentialBinding``
model to the sorted names of the bound fields. The web create form reads it to
show those fields above the credential section. A backend test compares it
with the binding models.

Usage (from ``backend/``), then format the file with oxfmt:
    python -m scripts.generate_credential_bound_fields
    cd ../web && bun run format
"""

import json
from pathlib import Path

from onyx.connectors.registry import CONNECTOR_CLASS_MAP

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "web"
    / "src"
    / "lib"
    / "connectors"
    / "credentialBoundFields.json"
)
REGENERATE_COMMAND = (
    "cd backend && python -m scripts.generate_credential_bound_fields"
    " && cd ../web && bun run format"
)


def build_credential_bound_fields() -> dict[str, list[str]]:
    """Source value to the sorted bound field names, for every source with a
    binding model."""
    bound_fields: dict[str, list[str]] = {}
    for source, mapping in CONNECTOR_CLASS_MAP.items():
        binding_class = mapping.config_class.credential_binding_class()
        if binding_class is None:
            continue
        bound_fields[source.value] = sorted(binding_class.model_fields)
    return dict(sorted(bound_fields.items()))


def main() -> None:
    SNAPSHOT_PATH.write_text(
        json.dumps(build_credential_bound_fields(), indent=2) + "\n"
    )
    print(f"Wrote {SNAPSHOT_PATH}. Run `bun run format` in web/ to format it.")


if __name__ == "__main__":
    main()
