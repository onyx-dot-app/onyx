# export openapi schema without having to start the actual web server

# helpful tips: https://github.com/fastapi/fastapi/issues/1173

import argparse
import json
import os
import subprocess
import sys

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

OPENAPI_VERSION = "3.1.0"


def go(
    filename: str, tagged_for_docs: str | None = None, *, snapshot: bool = False
) -> None:
    """Generate OpenAPI schema.

    By default outputs tag-stripped schema (for client generation).
    If tagged_for_docs is provided, also outputs the original tagged version for docs.
    """
    from onyx.main import app as app_fn

    app: FastAPI = app_fn()
    app.openapi_version = OPENAPI_VERSION
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )

    # Output tagged version for docs if requested
    if tagged_for_docs:
        with open(tagged_for_docs, "w") as f:
            json.dump(schema, f)
        print(f"Wrote tagged OpenAPI schema to {tagged_for_docs}")

    # Output stripped version (default) for client generation
    stripped = strip_tags_from_schema(schema)
    with open(filename, "w") as f:
        if snapshot:
            json.dump(stripped, f, indent=2, sort_keys=True)
            f.write("\n")
        else:
            json.dump(stripped, f)
    print(f"Wrote OpenAPI schema to {filename}.")
    if snapshot:
        print("Commit the snapshot with the API change. To regenerate it, run:")
        print("  prek run openapi-snapshot --all-files")


def strip_tags_from_schema(schema: dict) -> dict:
    """Strip tags from OpenAPI schema so openapi-generator puts all endpoints in DefaultApi."""
    import copy

    schema = copy.deepcopy(schema)

    # Remove tags from all operations
    if "paths" in schema:
        for path_item in schema["paths"].values():
            for operation in path_item.values():
                if isinstance(operation, dict) and "tags" in operation:
                    del operation["tags"]

    # Remove top-level tags definition
    if "tags" in schema:
        del schema["tags"]

    return schema


def generate_client(openapi_json_path: str, strip_tags: bool = True) -> None:
    """Generate Python client from OpenAPI schema using openapi-generator."""
    import tempfile

    output_dir = os.path.join(os.path.dirname(openapi_json_path), "onyx_openapi_client")

    # Optionally strip tags so all endpoints go under DefaultApi
    schema_path = openapi_json_path
    if strip_tags:
        with open(openapi_json_path) as f:
            schema = json.load(f)
        stripped = strip_tags_from_schema(schema)
        fd, schema_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(stripped, f)
        print(f"Stripped tags from schema, using temp file: {schema_path}")

    cmd = [
        "openapi-generator",
        "generate",
        "-i",
        schema_path,
        "-g",
        "python",
        "-o",
        output_dir,
        "--package-name",
        "onyx_openapi_client",
        "--skip-validate-spec",
        "--openapi-normalizer",
        "SIMPLIFY_ONEOF_ANYOF=true,SET_OAS3_NULLABLE=true",
    ]

    print("Running openapi-generator...")
    try:
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print(f"Generated Python client at {output_dir}")
        else:
            print(
                "Failed to generate Python client. See backend/tests/integration/README.md for setup instructions.",
                file=sys.stderr,
            )
    finally:
        # Clean up temp file if we created one
        if strip_tags and schema_path != openapi_json_path:
            os.unlink(schema_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export OpenAPI schema for Onyx API (does not require starting API server)"
    )
    parser.add_argument(
        "--filename", "-f", help="Filename to write to", default="openapi.json"
    )
    parser.add_argument(
        "--generate-python-client",
        action="store_true",
        help="Generate Python client schemas (needed for integration tests)",
    )
    parser.add_argument(
        "--tagged-for-docs",
        help="Also output a tagged version for API docs (specify output path)",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Use default Onyx settings and write sorted, indented JSON",
    )

    args = parser.parse_args()
    if args.snapshot:
        # Settings such as OAUTH_ENABLED add routes, so the snapshot uses defaults.
        os.environ.clear()
        # Stops LiteLLM from fetching its model cost map at import.
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

    go(args.filename, tagged_for_docs=args.tagged_for_docs, snapshot=args.snapshot)

    if args.generate_python_client:
        # Schema is already stripped by go(), no need to strip again
        generate_client(args.filename, strip_tags=False)


if __name__ == "__main__":
    main()
