"""Read-only deployment gate. Drain legacy writers before running this check."""

import argparse

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.skill_version import skill_version_repair_batch


def check_cutover(tenant_id: str) -> int:
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        drift = skill_version_repair_batch(session, None, drift_only=True)
        if drift:
            print(f"BLOCKED: legacy/version drift in tenant {tenant_id} (first batch):")
            for skill in drift:
                print(skill.id)
            return 1
    print(f"PASS: no legacy/version drift in tenant {tenant_id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    SqlEngine.init_engine(pool_size=1, max_overflow=0)
    return check_cutover(args.tenant_id)


if __name__ == "__main__":
    raise SystemExit(main())
