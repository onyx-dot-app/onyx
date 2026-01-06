"""
Transform OpenAPI schema for public documentation.

Filters endpoints tagged with "public", converts auth to Bearer token,
and removes internal parameters (tenant_id, db_session).

Usage:
    python scripts/transform_openapi_for_docs.py -i generated/openapi.json -o openapi_docs.json
"""

import argparse
import copy
import json
from typing import Any

PUBLIC_TAG = "public"
DOCS_SERVER_URL = "https://cloud.onyx.app/api"
INTERNAL_PARAMETERS = {"tenant_id", "db_session"}


def collect_schema_refs(obj: Any, refs: set[str]) -> None:
    """Recursively collect all $ref references from an object."""
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if ref.startswith("#/components/schemas/"):
                refs.add(ref.split("/")[-1])
        for value in obj.values():
            collect_schema_refs(value, refs)
    elif isinstance(obj, list):
        for item in obj:
            collect_schema_refs(item, refs)


def get_all_referenced_schemas(
    schemas: dict[str, Any], initial_refs: set[str]
) -> set[str]:
    """Get all schemas referenced by initial_refs, including nested references."""
    all_refs = set(initial_refs)
    to_process = list(initial_refs)

    while to_process:
        schema_name = to_process.pop()
        if schema_name not in schemas:
            continue

        new_refs: set[str] = set()
        collect_schema_refs(schemas[schema_name], new_refs)

        for ref in new_refs:
            if ref not in all_refs:
                all_refs.add(ref)
                to_process.append(ref)

    return all_refs


def remove_internal_properties_from_schema(schema: dict[str, Any]) -> None:
    """Recursively remove internal properties from a schema."""
    if not isinstance(schema, dict):
        return

    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name in list(schema["properties"].keys()):
            if prop_name in INTERNAL_PARAMETERS:
                del schema["properties"][prop_name]

        if "required" in schema and isinstance(schema["required"], list):
            schema["required"] = [
                r for r in schema["required"] if r not in INTERNAL_PARAMETERS
            ]
            if not schema["required"]:
                del schema["required"]

    for key in ["allOf", "oneOf", "anyOf"]:
        if key in schema and isinstance(schema[key], list):
            for item in schema[key]:
                remove_internal_properties_from_schema(item)

    if "items" in schema:
        remove_internal_properties_from_schema(schema["items"])

    if "additionalProperties" in schema and isinstance(
        schema["additionalProperties"], dict
    ):
        remove_internal_properties_from_schema(schema["additionalProperties"])


def remove_internal_parameters(spec: dict[str, Any]) -> None:
    """Remove internal parameters from all endpoints and schemas."""
    for path_data in spec.get("paths", {}).values():
        for method_data in path_data.values():
            if isinstance(method_data, dict) and "parameters" in method_data:
                method_data["parameters"] = [
                    p
                    for p in method_data["parameters"]
                    if not (
                        isinstance(p, dict) and p.get("name") in INTERNAL_PARAMETERS
                    )
                ]
                if not method_data["parameters"]:
                    del method_data["parameters"]

    for schema in spec.get("components", {}).get("schemas", {}).values():
        remove_internal_properties_from_schema(schema)


def transform_openapi(input_spec: dict[str, Any]) -> dict[str, Any]:
    """Transform the OpenAPI spec for public documentation."""
    output_spec: dict[str, Any] = {
        "openapi": input_spec.get("openapi", "3.1.0"),
        "info": {
            "title": "Onyx API",
            "description": "Onyx API for AI-powered enterprise search and chat",
            "version": input_spec.get("info", {}).get("version", "1.0.0"),
        },
        "servers": [{"url": DOCS_SERVER_URL}],
        "paths": {},
        "components": {
            "schemas": {},
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Authorization header with Bearer token",
                }
            },
        },
    }

    input_paths = input_spec.get("paths", {})
    initial_refs: set[str] = set()

    for path, path_data in input_paths.items():
        for method, method_data in path_data.items():
            if not isinstance(method_data, dict):
                continue

            if PUBLIC_TAG in method_data.get("tags", []):
                if path not in output_spec["paths"]:
                    output_spec["paths"][path] = {}

                endpoint = copy.deepcopy(method_data)
                if "security" in endpoint:
                    endpoint["security"] = [{"BearerAuth": []}]
                output_spec["paths"][path][method] = endpoint
                collect_schema_refs(method_data, initial_refs)

    input_schemas = input_spec.get("components", {}).get("schemas", {})
    all_refs = get_all_referenced_schemas(input_schemas, initial_refs)

    for schema_name in all_refs:
        if schema_name in input_schemas:
            output_spec["components"]["schemas"][schema_name] = copy.deepcopy(
                input_schemas[schema_name]
            )

    remove_internal_parameters(output_spec)

    return output_spec


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform OpenAPI schema for public documentation"
    )
    parser.add_argument(
        "--input", "-i", default="openapi.json", help="Input OpenAPI JSON file"
    )
    parser.add_argument(
        "--output", "-o", default="openapi_docs.json", help="Output OpenAPI JSON file"
    )
    args = parser.parse_args()

    with open(args.input) as f:
        input_spec = json.load(f)

    output_spec = transform_openapi(input_spec)

    with open(args.output, "w") as f:
        json.dump(output_spec, f, indent=2)

    endpoint_count = sum(len(m) for m in output_spec["paths"].values())
    schema_count = len(output_spec["components"]["schemas"])
    print(f"Wrote {args.output}: {endpoint_count} endpoints, {schema_count} schemas")


if __name__ == "__main__":
    main()
