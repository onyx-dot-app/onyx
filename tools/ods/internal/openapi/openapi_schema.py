"""Generate OpenAPI schema and Python client for Onyx API.

This script is bundled with the ods wheel and executed by the Go binary
to generate the OpenAPI schema without starting the full API server.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

# TODO: remove this once openapi fixes the anyof/none issues
OPENAPI_VERSION = "3.1.0"


def generate_schema(output_path: str) -> bool:
    """Generate OpenAPI schema to the specified path.

    Returns True on success, False on failure.
    """
    try:
        # Import here to avoid requiring backend dependencies when not generating schema
        from fastapi.openapi.utils import get_openapi
        from onyx.main import app as app_fn  # type: ignore
    except ImportError as e:
        print(f"Error: Failed to import required modules: {e}", file=sys.stderr)
        print(
            "Make sure you are running from a venv with onyx[backend] installed.",
            file=sys.stderr,
        )
        return False

    try:
        app: FastAPI = app_fn()
        app.openapi_version = OPENAPI_VERSION

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(
                get_openapi(
                    title=app.title,
                    version=app.version,
                    openapi_version=app.openapi_version,
                    description=app.description,
                    routes=app.routes,
                ),
                f,
                indent=2,
            )

        print(f"Wrote OpenAPI schema to {output_path}")
    except Exception as e:  # noqa: BLE001
        print(f"Error generating OpenAPI schema: {e}", file=sys.stderr)
        return False
    else:
        return True


def strip_tags_from_schema(openapi_json_path: str) -> str:
    """Strip tags from OpenAPI schema so openapi-generator puts all endpoints in DefaultApi.

    Returns the path to a temporary file with tags stripped.
    """
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


def generate_client(
    openapi_json_path: str, output_dir: str | None = None, strip_tags: bool = True
) -> bool:
    """Generate Python client from OpenAPI schema using openapi-generator-cli.

    Returns True on success, False on failure.
    """
    if output_dir is None:
        output_dir = str(Path(openapi_json_path).parent / "onyx_openapi_client")

    # Optionally strip tags so all endpoints go under DefaultApi
    schema_path = openapi_json_path
    if strip_tags:
        schema_path = strip_tags_from_schema(openapi_json_path)
        print(f"Stripped tags from schema, using temp file: {schema_path}")

    cmd = [
        "openapi-generator-cli",
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
        result = subprocess.run(cmd, check=False)  # noqa: S603

        if result.returncode == 0:
            print(f"Generated Python client at {output_dir}")
            return True
        print(
            "Failed to generate Python client. "
            "See backend/tests/integration/README.md for setup instructions.",
            file=sys.stderr,
        )
        return False
    finally:
        # Clean up temp file if we created one
        if strip_tags and schema_path != openapi_json_path:
            os.unlink(schema_path)


def main() -> int:  # noqa: PLR0911
    parser = argparse.ArgumentParser(
        description="Generate OpenAPI schema and Python client for Onyx API"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Schema subcommand
    schema_parser = subparsers.add_parser(
        "schema", help="Generate OpenAPI schema JSON file"
    )
    schema_parser.add_argument(
        "-o",
        "--output",
        default="openapi.json",
        help="Output path for the OpenAPI schema (default: openapi.json)",
    )

    # Client subcommand
    client_parser = subparsers.add_parser(
        "client", help="Generate Python client from OpenAPI schema"
    )
    client_parser.add_argument(
        "-i",
        "--input",
        default="openapi.json",
        help="Path to OpenAPI schema JSON (default: openapi.json)",
    )
    client_parser.add_argument(
        "-o",
        "--output",
        help="Output directory for the generated client (default: same dir as schema)",
    )

    # All subcommand (schema + client)
    all_parser = subparsers.add_parser(
        "all", help="Generate both OpenAPI schema and Python client"
    )
    all_parser.add_argument(
        "-o",
        "--output",
        default="openapi.json",
        help="Output path for the OpenAPI schema (default: openapi.json)",
    )
    all_parser.add_argument(
        "--client-output",
        help="Output directory for the generated client (default: same dir as schema)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "schema":
        return 0 if generate_schema(args.output) else 1

    if args.command == "client":
        return 0 if generate_client(args.input, args.output) else 1

    if args.command == "all":
        if not generate_schema(args.output):
            return 1
        if not generate_client(args.output, args.client_output):
            return 1
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
