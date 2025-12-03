# export openapi schema without having to start the actual web server

# helpful tips: https://github.com/fastapi/fastapi/issues/1173

import argparse
import json
import os
import subprocess

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from onyx.main import app as app_fn

# TODO: remove this once openapi fixes the anyof/none issues
OPENAPI_VERSION = "3.0.3"


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


def generate_client(openapi_json_path: str) -> None:
    """Generate Python client from OpenAPI schema using openapi-generator."""
    output_dir = os.path.join(os.path.dirname(openapi_json_path), "onyx_openapi_client")

    cmd = [
        "openapi-generator",
        "generate",
        "-i",
        openapi_json_path,
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
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"Generated Python client at {output_dir}")
    else:
        print("Failed to generate Python client.")
        print("See backend/tests/integration/README.md for setup instructions.")


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
