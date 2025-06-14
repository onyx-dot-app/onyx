# export openapi schema without having to start the actual web server

# helpful tips: https://github.com/fastapi/fastapi/issues/1173

import argparse
import json
import os

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Force full enterprise edition schema to be generated
os.environ["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"

# NOTE(rkuo): we're conditionally including endpoints based on auth type
# looks like a time bomb / bad design
os.environ["AUTH_TYPE"] = "basic"

if True:  # noqa: E402
    from onyx.main import app as app_fn


def go(filenames: list[str]) -> None:
    app: FastAPI = app_fn()
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    for filename in filenames:
        with open(filename, "w") as f:
            json.dump(openapi_schema, f, indent=2)
        print(f"Wrote OpenAPI schema to {filename}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export OpenAPI schema for Onyx API (does not require starting API server)"
    )
    parser.add_argument(
        "--filenames",
        "-f",
        help="Filenames to write to. Can specify multiple delimited by spaces.",
        nargs="+",
        default=["openapi.json"],
    )

    args = parser.parse_args()
    go(args.filenames)


if __name__ == "__main__":
    main()
