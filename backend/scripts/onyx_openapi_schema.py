# export openapi schema without having to start the actual web server

# helpful tips: https://github.com/fastapi/fastapi/issues/1173

import argparse
import json

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export OpenAPI schema for Onyx API (does not require starting API server)"
    )
    parser.add_argument(
        "--filename", "-f", help="Filename to write to", default="openapi.json"
    )

    args = parser.parse_args()
    go(args.filename)


if __name__ == "__main__":
    main()
