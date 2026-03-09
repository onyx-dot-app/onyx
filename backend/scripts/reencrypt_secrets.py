"""Re-encrypt secrets under the current ENCRYPTION_KEY_SECRET.

Decrypts all encrypted columns using the old key (or raw decode if the old key
is empty), then re-encrypts them with the current ENCRYPTION_KEY_SECRET.

Usage (docker):
    docker exec -it onyx-api_server-1 \
        python -m scripts.reencrypt_secrets --old-key "previous-key"

Usage (kubernetes):
    kubectl exec -it <pod> -- \
        python -m scripts.reencrypt_secrets --old-key "previous-key"

Omit --old-key (or pass "") if secrets were not previously encrypted.

For multi-tenant deployments, pass --tenant-id to target a specific tenant,
or --all-tenants to iterate every tenant.
"""

import argparse
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.db.rotate_encryption_key import rotate_encryption_key  # noqa: E402
from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from onyx.utils.variable_functionality import global_version  # noqa: E402
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA  # noqa: E402


def _run_for_tenant(tenant_id: str, old_key: str | None, dry_run: bool = False) -> None:
    print(f"Re-encrypting secrets for tenant: {tenant_id}")
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        results = rotate_encryption_key(db_session, old_key=old_key, dry_run=dry_run)

    if results:
        for col, count in results.items():
            print(
                f"  {col}: {count} row(s) {'would be ' if dry_run else ''}re-encrypted"
            )
    else:
        print("No rows needed re-encryption.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt secrets under the current encryption key."
    )
    parser.add_argument(
        "--old-key",
        default=None,
        help="Previous encryption key. Omit or pass empty string if not applicable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be re-encrypted without making changes.",
    )

    tenant_group = parser.add_mutually_exclusive_group()
    tenant_group.add_argument(
        "--tenant-id",
        default=None,
        help="Target a specific tenant schema.",
    )
    tenant_group.add_argument(
        "--all-tenants",
        action="store_true",
        help="Iterate all tenants.",
    )

    args = parser.parse_args()

    old_key = args.old_key if args.old_key else None

    global_version.set_ee()
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    if args.dry_run:
        print("DRY RUN — no changes will be made")

    if args.all_tenants:
        tenant_ids = get_all_tenant_ids()
        print(f"Found {len(tenant_ids)} tenant(s)")
        failed_tenants: list[str] = []
        for tid in tenant_ids:
            try:
                _run_for_tenant(tid, old_key, dry_run=args.dry_run)
            except Exception as e:
                print(f"  ERROR for tenant {tid}: {e}")
                failed_tenants.append(tid)
        if failed_tenants:
            print(f"FAILED tenants ({len(failed_tenants)}): {failed_tenants}")
            sys.exit(1)
    else:
        tenant_id = args.tenant_id or POSTGRES_DEFAULT_SCHEMA
        _run_for_tenant(tenant_id, old_key, dry_run=args.dry_run)

    print("Done.")


if __name__ == "__main__":
    main()
