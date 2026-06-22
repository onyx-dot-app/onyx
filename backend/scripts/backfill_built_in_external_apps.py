"""Backfill Onyx-managed built-in external apps across tenants.

``provision_built_in_external_apps`` seeds built-in apps per tenant but won't
update an existing app's gateway config on a re-run, so tenants don't pick up
new app types or changed URL patterns / auth templates. This script is the
manual backfill: for every selected tenant it makes the DB match operator config
(the ``EXT_APP_<APP_TYPE>_<FIELD>`` env vars + the code-defined provider):

  * missing app  -> created (disabled, so an admin still opts in)
  * existing app -> name, description, upstream_url_patterns, auth_template and
                    organization_credentials are overwritten from config.

Preserved per tenant (admin decisions, not operator config): the app's
enabled/disabled state and its per-action policy overrides. Credentials are left
untouched for app types with no env vars configured rather than wiped.

Usage (kubernetes):
    kubectl exec -it <api-server-pod> -- \
        python -m scripts.backfill_built_in_external_apps --all-tenants

    # Preview only, no writes:
    python -m scripts.backfill_built_in_external_apps --all-tenants --dry-run

    # A single app type, a single tenant:
    python -m scripts.backfill_built_in_external_apps \
        --app-type SLACK --tenant-id tenant_<uuid>
"""

import argparse
import os
import sys
from collections.abc import Iterator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from pydantic import BaseModel  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from onyx.db.enums import ExternalAppType  # noqa: E402
from onyx.db.external_app import create_external_app  # noqa: E402
from onyx.db.external_app import get_built_in_external_app  # noqa: E402
from onyx.db.external_app import update_external_app  # noqa: E402
from onyx.db.utils import UNSET  # noqa: E402
from onyx.db.utils import UnsetType  # noqa: E402
from onyx.external_apps.models import BuiltInExternalAppDescriptor  # noqa: E402
from onyx.external_apps.providers.registry import (  # noqa: E402
    fetch_onyx_managed_built_in_apps,
)
from onyx.external_apps.providers.registry import (  # noqa: E402
    get_onyx_managed_provider,
)
from onyx.utils.variable_functionality import global_version  # noqa: E402
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA  # noqa: E402

DEFAULT_WORKERS = 16

# Descriptor (code-defined) + env-sourced credentials, None when unconfigured.
# Env is global, so this is resolved once and reused across tenants.
ManagedAppConfig = tuple[BuiltInExternalAppDescriptor, dict[str, str] | None]


class TenantResult(BaseModel):
    """Outcome of backfilling every selected app for one tenant.

    ``report`` is the pre-rendered, multi-line block for this tenant, buffered
    so concurrent tenants don't interleave their lines on stdout.
    """

    tenant_id: str
    ok: bool
    report: str


def _configured_credentials(
    descriptor: BuiltInExternalAppDescriptor,
) -> dict[str, str] | None:
    provider = get_onyx_managed_provider(descriptor.app_type)
    return provider.configured_managed_credentials() if provider else None


def _select_managed_apps(
    app_type: ExternalAppType | None,
) -> list[ManagedAppConfig]:
    """Resolve the Onyx-managed apps to backfill and their env credentials.

    ``app_type`` None selects every Onyx-managed built-in. A specific type that
    isn't one is a hard error — there's nothing to backfill from .env for it.
    """
    descriptors = fetch_onyx_managed_built_in_apps()
    if app_type is not None:
        descriptors = [d for d in descriptors if d.app_type == app_type]
        if not descriptors:
            raise SystemExit(
                f"'{app_type.value}' is not an Onyx-managed built-in app type; "
                "nothing to backfill from .env."
            )

    return [(d, _configured_credentials(d)) for d in descriptors]


class Backfiller:
    """Applies operator config to built-in external apps for selected tenants.

    Holds the run-wide config (the resolved apps + dry-run flag) so it doesn't
    have to be threaded through every call. ``run`` is a generator yielding one
    ``TenantResult`` per tenant as it completes, hiding the thread pool from the
    caller.
    """

    def __init__(self, managed_apps: list[ManagedAppConfig], dry_run: bool) -> None:
        self._managed_apps = managed_apps
        self._dry_run = dry_run

    def run(self, tenant_ids: list[str], workers: int) -> Iterator[TenantResult]:
        """Yield a result per tenant as work completes (nondeterministic order)."""
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._run_tenant, tid) for tid in tenant_ids]
            for future in as_completed(futures):
                yield future.result()

    def _run_tenant(self, tenant_id: str) -> TenantResult:
        lines = [f"Tenant: {tenant_id}"]
        all_ok = True
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                for descriptor, credentials in self._managed_apps:
                    app = descriptor.app_type.value
                    try:
                        status = self._backfill_app(db_session, descriptor, credentials)
                        lines.append(f"  {app}: {status}")
                    except Exception as e:
                        db_session.rollback()
                        all_ok = False
                        lines.append(f"  {app}: ERROR — {e}")
        except Exception as e:
            all_ok = False
            lines.append(f"  ERROR — {e}")
        return TenantResult(tenant_id=tenant_id, ok=all_ok, report="\n".join(lines))

    def _backfill_app(
        self,
        db_session: Session,
        descriptor: BuiltInExternalAppDescriptor,
        credentials: dict[str, str] | None,
    ) -> str:
        """Make one tenant's row for ``descriptor.app_type`` match operator config.

        Returns a short human-readable status. Commits its own change so a later
        app's failure can't roll this one back.
        """
        app_type = descriptor.app_type
        existing = get_built_in_external_app(db_session, app_type)

        # UNSET leaves stored credentials untouched for types with no env vars set.
        org_credentials: dict[str, str] | UnsetType = (
            credentials if credentials is not None else UNSET
        )
        cred_note = "creds replaced" if credentials is not None else "creds left as-is"

        if existing is not None:
            if self._dry_run:
                return (
                    f"would update (id={existing.id}; config + {cred_note}; "
                    "enabled state preserved)"
                )
            update_external_app(
                db_session,
                existing.id,
                app_type,
                name=descriptor.name,
                description=descriptor.description,
                upstream_url_patterns=list(descriptor.upstream_url_patterns),
                auth_template=dict(descriptor.auth_template),
                organization_credentials=org_credentials,
                action_policies=UNSET,
            )
            db_session.commit()
            return f"updated (id={existing.id}; {cred_note})"

        if self._dry_run:
            return f"would create (disabled; {cred_note})"
        app = create_external_app(
            db_session=db_session,
            name=descriptor.name,
            description=descriptor.description,
            bundle_file_id="",
            bundle_sha256="",
            app_type=app_type,
            upstream_url_patterns=list(descriptor.upstream_url_patterns),
            auth_template=dict(descriptor.auth_template),
            organization_credentials=credentials or {},
            enabled=False,
            is_public=True,
            action_policies=None,
        )
        db_session.commit()
        return f"created (id={app.id}; disabled; {cred_note})"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill Onyx-managed built-in external apps across tenants, "
            "replacing DB gateway config + credentials with operator config."
        )
    )
    parser.add_argument(
        "--app-type",
        default=None,
        help=(
            "Restrict to one built-in app type (e.g. SLACK, LINEAR, GITHUB, "
            "GMAIL, GOOGLE_CALENDAR, GOOGLE_DRIVE). Default: all Onyx-managed "
            "built-in apps."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing anything.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            f"Number of tenants to backfill concurrently (default: {DEFAULT_WORKERS})."
        ),
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
        help="Iterate every tenant.",
    )
    return parser.parse_args()


def _resolve_app_type(raw: str | None) -> ExternalAppType | None:
    if raw is None:
        return None
    try:
        return ExternalAppType(raw.strip().upper())
    except ValueError:
        valid = ", ".join(t.value for t in ExternalAppType if t.is_built_in)
        raise SystemExit(f"Unknown app type '{raw}'. Built-in types: {valid}.")


def _resolve_tenant_ids(args: argparse.Namespace) -> list[str]:
    if args.all_tenants:
        return get_all_tenant_ids()
    return [args.tenant_id or POSTGRES_DEFAULT_SCHEMA]


def _print_preamble(managed_apps: list[ManagedAppConfig], dry_run: bool) -> None:
    app_names = [d.app_type.value for d, _ in managed_apps]
    print(f"Backfilling {', '.join(app_names)} ({len(app_names)} app type(s))")
    unconfigured = [d.app_type.value for d, creds in managed_apps if creds is None]
    if unconfigured:
        print(
            "  NOTE: no env credentials configured for "
            f"{', '.join(unconfigured)} — stored credentials left untouched "
            "(config/URL patterns/auth template still applied)."
        )
    if dry_run:
        print("DRY RUN — no changes will be made")


def main() -> None:
    args = _parse_args()
    app_type = _resolve_app_type(args.app_type)

    workers = max(1, args.workers)
    global_version.set_ee()
    SqlEngine.init_engine(pool_size=workers, max_overflow=2)

    managed_apps = _select_managed_apps(app_type)
    _print_preamble(managed_apps, args.dry_run)

    tenant_ids = _resolve_tenant_ids(args)
    total = len(tenant_ids)
    workers = max(1, min(workers, total))
    print(f"Processing {total} tenant(s) with {workers} worker(s)\n")

    backfiller = Backfiller(managed_apps, args.dry_run)
    failed_tenants: list[str] = []
    for done, result in enumerate(backfiller.run(tenant_ids, workers), start=1):
        print(f"[{done}/{total}] {result.report}")
        if not result.ok:
            failed_tenants.append(result.tenant_id)

    print()
    if failed_tenants:
        print(f"FAILED tenants ({len(failed_tenants)}): {failed_tenants}")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
