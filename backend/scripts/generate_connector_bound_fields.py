"""Writes web/src/lib/connectors/connectorBoundFields.json.

The file maps each source in the connector registry to its connector config
fields that are not credential-bound, with each field's type, whether it is
required, and its default. Together with ``credentialBoundFields.json`` it
covers every ``ConnectorConfig`` field. A backend test compares it with the
config models.

A default appears only when the model hardcodes it. A default read from
``onyx.configs`` or the environment depends on the deployment, so it is left
out.

Usage (from ``backend/``), then format the file with oxfmt:
    python -m scripts.generate_connector_bound_fields
    cd ../web && bun run format
"""

import ast
import importlib
import inspect
import json
import textwrap
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.registry import CONNECTOR_CLASS_MAP

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "web"
    / "src"
    / "lib"
    / "connectors"
    / "connectorBoundFields.json"
)
REGENERATE_COMMAND = (
    "cd backend && python -m scripts.generate_connector_bound_fields"
    " && cd ../web && bun run format"
)

# A default that reads one of these depends on the deployment.
_DEPLOYMENT_MODULE_PREFIX = "onyx.configs"


def _deployment_names(module_name: str) -> set[str]:
    """Names in a module whose value depends on the deployment: the ways to
    read the environment, names imported from ``onyx.configs``, and module
    constants computed from either."""
    tree = ast.parse(inspect.getsource(importlib.import_module(module_name)))
    names: set[str] = {"os", "environ", "getenv"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            _DEPLOYMENT_MODULE_PREFIX
        ):
            names.update(alias.asname or alias.name for alias in node.names)
    # A constant may build on an earlier one, so repeat until nothing changes.
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_names = {t.id for t in targets if isinstance(t, ast.Name)}
            if target_names - names and _references(node.value, names):
                names |= target_names
                changed = True
    return names


def _references(expression: ast.expr, names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id in names for node in ast.walk(expression)
    )


def _default_expression(config_class: type, field_name: str) -> ast.expr | None:
    """The source expression of a field's default, from the class that
    declares the field."""
    for klass in config_class.__mro__:
        if field_name not in klass.__dict__.get("__annotations__", {}):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(klass)))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == field_name
            ):
                return node.value
        return None
    return None


def _is_deployment_default(config_class: type, field_name: str) -> bool:
    expression = _default_expression(config_class, field_name)
    if expression is None:
        return False
    return _references(expression, _deployment_names(config_class.__module__))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _schema_type(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """A property's type, nullability, enum values and array items."""
    if "$ref" in prop:
        prop = defs[prop["$ref"].split("/")[-1]]
    if "anyOf" in prop:
        variants = [v for v in prop["anyOf"] if v.get("type") != "null"]
        nullable = len(variants) < len(prop["anyOf"])
        resolved = [_schema_type(v, defs) for v in variants]
        types = sorted({r["type"] for r in resolved if isinstance(r["type"], str)})
        # An int-or-float field takes any number.
        if set(types) == {"integer", "number"}:
            types = ["number"]
        merged: dict[str, Any] = {"type": types[0] if len(types) == 1 else types}
        for r in resolved:
            for key in ("enum", "items"):
                if key in r:
                    merged[key] = r[key]
        if nullable:
            merged["nullable"] = True
        return merged
    result: dict[str, Any] = {"type": prop.get("type", "object")}
    if "enum" in prop:
        result["enum"] = prop["enum"]
    if "items" in prop:
        result["items"] = _schema_type(prop["items"], defs)
    return result


def _field_metadata(
    config_class: type[ConnectorConfig],
    name: str,
    field: FieldInfo,
    schema: dict[str, Any],
) -> dict[str, Any]:
    metadata: dict[str, Any] = _schema_type(
        schema["properties"][name], schema.get("$defs", {})
    )
    required: bool = field.is_required()
    metadata["required"] = required
    if not required and not _is_deployment_default(config_class, name):
        metadata["default"] = _json_value(field.get_default(call_default_factory=True))
    return metadata


def build_connector_bound_fields() -> dict[str, dict[str, dict[str, Any]]]:
    """Source value to its config fields that are not bound to the credential,
    each with its metadata, for every source with at least one such field."""
    connector_fields: dict[str, dict[str, dict[str, Any]]] = {}
    for source, mapping in CONNECTOR_CLASS_MAP.items():
        config_class = mapping.config_class
        binding_class = config_class.credential_binding_class()
        bound: set[str] = (
            set(binding_class.model_fields) if binding_class is not None else set()
        )
        schema: dict[str, Any] = config_class.model_json_schema()
        fields = {
            name: _field_metadata(config_class, name, field, schema)
            for name, field in sorted(config_class.model_fields.items())
            if name not in bound
        }
        if fields:
            connector_fields[source.value] = fields
    return dict(sorted(connector_fields.items()))


def main() -> None:
    SNAPSHOT_PATH.write_text(
        json.dumps(build_connector_bound_fields(), indent=2) + "\n"
    )
    print(f"Wrote {SNAPSHOT_PATH}. Run `bun run format` in web/ to format it.")


if __name__ == "__main__":
    main()
