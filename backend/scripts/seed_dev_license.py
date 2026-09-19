"""Seed a dev license blob into the DB for CI test environments.

Usage (docker):
    docker exec -e ONYX_DEV_LICENSE onyx-api_server-1 \
        python -m scripts.seed_dev_license

Reads ONYX_DEV_LICENSE from the environment. Empty values no-op so the
script can be invoked unconditionally (e.g. local dev runs without a
license to hand). Accepts both PEM-armored and raw base64 license blobs;
verifies the RSA-4096 signature before persisting.
"""

import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from ee.onyx.db.license import upsert_license  # noqa: E402
from ee.onyx.utils.license import (  # noqa: E402
    normalize_license_file,
    verify_license_signature,
)
from onyx.db.engine.sql_engine import (  # noqa: E402
    SqlEngine,
    get_session_with_current_tenant,
)


def main() -> None:
    blob = os.environ.get("ONYX_DEV_LICENSE", "").strip()
    if not blob:
        print("ONYX_DEV_LICENSE empty: skipping license seed")
        return

    license_data = normalize_license_file(blob)
    verify_license_signature(license_data)

    SqlEngine.init_engine(pool_size=1, max_overflow=0)
    with get_session_with_current_tenant() as db_session:
        upsert_license(db_session, license_data)

    print("Dev license seeded")


if __name__ == "__main__":
    main()
