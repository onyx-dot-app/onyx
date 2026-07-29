"""Populate `oauth_name` / `account_id` on `public.user_tenant_mapping`.

Reads each tenant's `oauth_account` table and copies the IdP subject onto that
user's mapping row, so tenant resolution can key on a stable identity instead of
the email string.

Only fills rows whose `oauth_name` is still NULL, so it is safe to re-run and
will not overwrite values written by a live login.

Usage (kubernetes):
    kubectl exec -it <pod> -- \
        python -m scripts.backfill_user_tenant_mapping_oauth --all-tenants --dry-run
"""

import argparse
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from sqlalchemy import select  # noqa: E402

from onyx.db.engine.sql_engine import (  # noqa: E402
    SqlEngine,
    get_session_with_shared_schema,
    get_session_with_tenant,
)
from onyx.db.models import User, UserTenantMapping  # noqa: E402
from onyx.utils.variable_functionality import global_version  # noqa: E402


def _tenant_ids_from_mapping() -> list[str]:
    """Every tenant with at least one mapping row, including those on
    non-default shards."""
    with get_session_with_shared_schema() as db_session:
        rows = db_session.execute(select(UserTenantMapping.tenant_id).distinct()).all()
    return sorted(tenant_id for (tenant_id,) in rows)


def _oauth_identities(tenant_id: str) -> dict[str, tuple[str, str]]:
    """email -> (oauth_name, account_id) for users with exactly one OAuth account.

    Users with several linked providers are skipped: the mapping row holds one
    identity, and picking between them is a judgment call this sweep shouldn't make.
    """
    by_email: dict[str, tuple[str, str]] = {}
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        users = (
            db_session.execute(select(User).where(User.oauth_accounts.any()))
            .scalars()
            .unique()
            .all()
        )

        for user in users:
            accounts = user.oauth_accounts
            if len(accounts) > 1:
                print(f"    skipping {user.email}: multiple linked OAuth accounts")
                continue
            if not accounts:
                continue
            by_email[user.email] = (accounts[0].oauth_name, accounts[0].account_id)

    return by_email


def _run_for_tenant(tenant_id: str, dry_run: bool) -> int:
    identities = _oauth_identities(tenant_id)
    if not identities:
        return 0

    updated = 0
    with get_session_with_shared_schema() as db_session:
        mappings = (
            db_session.execute(
                select(UserTenantMapping).where(
                    UserTenantMapping.tenant_id == tenant_id,
                    UserTenantMapping.oauth_name.is_(None),
                )
            )
            .scalars()
            .all()
        )

        for mapping in mappings:
            identity = identities.get(mapping.email)
            if identity is None:
                continue

            if dry_run:
                print(f"    would set {mapping.email} -> {identity}")
            else:
                mapping.oauth_name, mapping.account_id = identity
            updated += 1

        if not dry_run:
            db_session.commit()

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", help="Backfill a single tenant.")
    parser.add_argument(
        "--all-tenants", action="store_true", help="Backfill every tenant."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report changes without writing."
    )
    args = parser.parse_args()

    if not args.tenant_id and not args.all_tenants:
        parser.error("pass --tenant-id or --all-tenants")

    global_version.set_ee()
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    if args.dry_run:
        print("DRY RUN - no changes will be made")

    tenant_ids = [args.tenant_id] if args.tenant_id else _tenant_ids_from_mapping()
    if not tenant_ids:
        print("No mapping rows found - nothing to backfill")
        return

    print(f"Found {len(tenant_ids)} tenant(s)")

    total = 0
    failed: list[str] = []
    for tenant_id in tenant_ids:
        try:
            count = _run_for_tenant(tenant_id, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ERROR for tenant {tenant_id}: {e}")
            failed.append(tenant_id)
            continue

        if count:
            print(f"  {tenant_id}: {count} row(s)")
        total += count

    print(f"Backfilled {total} mapping row(s)")
    if failed:
        print(f"FAILED tenants ({len(failed)}): {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
