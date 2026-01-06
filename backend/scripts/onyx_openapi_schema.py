# export openapi schema without having to start the actual web server

# helpful tips: https://github.com/fastapi/fastapi/issues/1173

import argparse
import json
import os
import subprocess
import sys

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from onyx.main import app as app_fn

OPENAPI_VERSION = "3.1.0"


def go(filename: str) -> None:
    with open(filename, "w") as f:
        app: FastAPI = app_fn()
        app.openapi_version = OPENAPI_VERSION
        json.dump(
            get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            ),
            f,
        )

    print(f"Wrote OpenAPI schema to {filename}.")


def strip_tags_from_schema(openapi_json_path: str) -> str:
    """Strip tags from OpenAPI schema so openapi-generator puts all endpoints in DefaultApi.

    Returns the path to a temporary file with tags stripped.
    """
    import tempfile

    with open(openapi_json_path) as f:
        schema = json.load(f)

    # Remove tags from all operations
    if "paths" in schema:
        for path_item in schema["paths"].values():
            for operation in path_item.values():
                if isinstance(operation, dict) and "tags" in operation:
                    del operation["tags"]

    # Remove top-level tags definition
    if "tags" in schema:
        del schema["tags"]

    # Write to a temp file
    fd, temp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(schema, f)

    return temp_path


def generate_client(openapi_json_path: str, strip_tags: bool = True) -> None:
    """Generate Python client from OpenAPI schema using openapi-generator."""
    output_dir = os.path.join(os.path.dirname(openapi_json_path), "onyx_openapi_client")

    # Optionally strip tags so all endpoints go under DefaultApi
    schema_path = openapi_json_path
    if strip_tags:
        schema_path = strip_tags_from_schema(openapi_json_path)
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
                "Failed to generate Python client. "
                "See backend/tests/integration/README.md for setup instructions.",
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

    args = parser.parse_args()
    go(args.filename)

    if args.generate_python_client:
        generate_client(args.filename)


if __name__ == "__main__":
    main()
