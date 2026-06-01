"""Provision / refresh Onyx-managed built-in external apps across all tenants.

Run manually by an operator: at rollout (to backfill tenants provisioned before
this feature existed) and after rotating the Onyx-owned OAuth credentials. Reads
the operator credential config from the ``MANAGED_EXTERNAL_APP_CREDENTIALS`` env
var, then for every tenant provisions each built-in app (disabled) and refreshes
the credentials of already-provisioned apps in place. Idempotent — re-running is
safe and never wipes credentials for an app the config no longer mentions.

Usage (docker):
    docker exec -e MANAGED_EXTERNAL_APP_CREDENTIALS onyx-api_server-1 \
        python -m scripts.reconcile_managed_external_apps
"""

import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from ee.onyx.server.tenants.provisioning import (  # noqa: E402
    provision_built_in_external_apps,
)
from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR  # noqa: E402


def main() -> None:
    SqlEngine.init_engine(pool_size=2, max_overflow=0)

    tenant_ids = get_all_tenant_ids()
    print(f"Reconciling managed external apps across {len(tenant_ids)} tenant(s)")

    failures = 0
    for tenant_id in tenant_ids:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                provision_built_in_external_apps(db_session)
            print(f"  reconciled {tenant_id}")
        except Exception as e:
            failures += 1
            print(f"  FAILED {tenant_id}: {e}")
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    print(f"Done ({failures} failure(s))")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
