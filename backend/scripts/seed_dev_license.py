"""Seed a dev license blob into the DB for CI test environments.

Usage:
    ONYX_DEV_LICENSE="$(cat license.lic)" python -m scripts.seed_dev_license

Reads ONYX_DEV_LICENSE from the environment. If empty, no-ops so fork PRs
that don't have access to the secret can still boot the stack.

Accepts both PEM-armored and raw base64 license blobs. Verifies the RSA-4096
signature before persisting.
"""

import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from ee.onyx.db.license import upsert_license  # noqa: E402
from ee.onyx.utils.license import verify_license_signature  # noqa: E402
from onyx.db.engine.sql_engine import get_session_with_current_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402

_PEM_BEGIN = "-----BEGIN ONYX LICENSE-----"
_PEM_END = "-----END ONYX LICENSE-----"


def _strip_pem_delimiters(content: str) -> str:
    content = content.strip()
    if content.startswith(_PEM_BEGIN) and content.endswith(_PEM_END):
        lines = content.split("\n")
        return "\n".join(lines[1:-1]).strip()
    return content


def main() -> None:
    blob = os.environ.get("ONYX_DEV_LICENSE", "").strip()
    if not blob:
        print("ONYX_DEV_LICENSE empty: skipping license seed", file=sys.stderr)
        return

    license_data = _strip_pem_delimiters(blob).strip()

    try:
        _payload = verify_license_signature(license_data)
    except ValueError as e:
        print(f"License signature verification failed: {e}", file=sys.stderr)
        sys.exit(1)

    SqlEngine.init_engine(pool_size=1, max_overflow=0)
    with get_session_with_current_tenant() as db:
        upsert_license(db, license_data)

    print("Dev license seeded", file=sys.stderr)


if __name__ == "__main__":
    main()
