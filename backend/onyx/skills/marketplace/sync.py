"""Sync a GitHub marketplace: read the repository, stage the bundles that
change, write every change of the read in one transaction, then delete the
files nothing uses and push to the affected sandboxes.

One sync runs at a time for each marketplace. A sync asked for while one runs
sets the "sync again" mark, and the running sync goes again. A holder that
stops with the mark set starts a follow-up task.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

from fastapi import BackgroundTasks

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.marketplace import (
    apply_marketplace_sync__no_commit,
    get_github_marketplace,
    list_synced_plugins,
    record_marketplace_error__no_commit,
    request_marketplace_sync__no_commit,
    take_marketplace_sync_request__no_commit,
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.integrations.github_auth import github_authorization_for
from onyx.skills.ingest import delete_bundle_blob, store_version_content
from onyx.skills.ingest_from_github import read_repository_archive
from onyx.skills.marketplace.compare import plan_marketplace_sync
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CompleteMarketplace,
    GitHubRepoSource,
    MarketplaceRead,
    MarketplaceSyncResult,
    MarketplaceSyncStatus,
    ReadyPlugin,
    RemotePlugin,
    UnsupportedPlugin,
)
from onyx.skills.marketplace.provider import (
    REMOTE_REPOSITORY_MAX_COUNT,
    MarketplaceProviderAdapter,
    marketplace_adapter,
    marketplace_config,
)
from onyx.skills.marketplace.reader import build_entry_bundle, read_marketplace
from onyx.skills.models import PluginVersionContent
from onyx.skills.push import push_skills_and_commit
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_in_background
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

SYNC_LOCK_TIMEOUT_SECONDS: Final = 30 * 60
# Runs after this time do not start again for the "sync again" mark.
SYNC_TIME_BUDGET_SECONDS: Final = 20 * 60
SYNC_TASK_EXPIRES_SECONDS: Final = 60 * 60
# A mark this old outlived the lock of the task that should take it.
SYNC_REQUEST_STALE_SECONDS: Final = SYNC_LOCK_TIMEOUT_SECONDS + 5 * 60
LOGIN_GONE_ERROR: Final = (
    "The login user of this marketplace is gone. Replace the login."
)
SYNC_FAILED_ERROR: Final = "The sync failed. Try again."
_BUNDLE_CLEANUP = "marketplace bundle cleanup"


def _sync_lock_name(marketplace_id: UUID) -> str:
    return f"marketplace_sync:{marketplace_id}"


def _resolve_remote_entries(
    entries: tuple[ReadyPlugin | BlockedPlugin | UnsupportedPlugin | RemotePlugin, ...],
    adapter: MarketplaceProviderAdapter,
) -> list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin]:
    """Fetch each repository that remote entries name, at most
    ``REMOTE_REPOSITORY_MAX_COUNT`` per sync, and build their bundles."""
    repositories: dict[GitHubRepoSource, dict[str, bytes] | OnyxError] = {}
    resolved: list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin] = []
    for entry in entries:
        if not isinstance(entry, RemotePlugin):
            resolved.append(entry)
            continue
        repository_key = entry.source.model_copy(update={"path": None})
        if (
            repository_key not in repositories
            and len(repositories) >= REMOTE_REPOSITORY_MAX_COUNT
        ):
            resolved.append(
                BlockedPlugin(
                    entry_key=entry.entry_key,
                    path=None,
                    reason="The marketplace names more than "
                    f"{REMOTE_REPOSITORY_MAX_COUNT} other repositories.",
                )
            )
            continue
        if repository_key not in repositories:
            try:
                repositories[repository_key] = adapter.fetch_remote(entry.source)
            except OnyxError as exc:
                repositories[repository_key] = exc
        files = repositories[repository_key]
        if isinstance(files, OnyxError):
            resolved.append(
                BlockedPlugin(
                    entry_key=entry.entry_key,
                    path=None,
                    reason=f"{entry.source.owner}/{entry.source.repo}: {files.detail}",
                )
            )
            continue
        resolved.append(
            build_entry_bundle(
                files, entry.source.path or "", entry.entry, entry.entry_key
            )
        )
    return resolved


def read_marketplace_repository(
    adapter: MarketplaceProviderAdapter, folder: str | None
) -> MarketplaceRead:
    """Read the marketplace at the newest commit of its ref. Raises OnyxError
    when GitHub fails; a bad marketplace is a read with a failure."""
    revision = adapter.resolve_revision()
    archive = adapter.fetch(revision)
    read = read_marketplace(
        read_repository_archive(archive.archive_bytes), folder, archive.tree_shas
    )
    if not isinstance(read, CompleteMarketplace):
        return MarketplaceRead(
            revision=revision,
            tree_shas=archive.tree_shas,
            name=None,
            failure=read.reason,
            entries=[],
        )
    return MarketplaceRead(
        revision=revision,
        tree_shas=archive.tree_shas,
        name=read.name,
        failure=None,
        entries=_resolve_remote_entries(read.entries, adapter),
    )


def _stage(
    entries: list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin],
    keys: set[str],
) -> dict[str, PluginVersionContent]:
    """Store the bundle of each entry in ``keys``. On a failure, deletes the
    bundles it stored."""
    file_store = get_default_file_store()
    staged: dict[str, PluginVersionContent] = {}
    try:
        for entry in entries:
            if not isinstance(entry, ReadyPlugin) or entry.entry_key not in keys:
                continue
            bundle = entry.bundle
            staged[entry.entry_key] = store_version_content(
                bundle.content,
                display_name=f"{bundle.manifest.name}.zip",
                skills=[skill.content for skill in bundle.skills],
                file_store=file_store,
                manifest=bundle.manifest,
                needs=bundle.needs,
            ).model_copy(update={"source_tree_sha": entry.tree_sha})
    except Exception:
        for content in staged.values():
            delete_bundle_blob(file_store, content.bundle_file_id)
        raise
    return staged


def _record_failure(marketplace_id: UUID, error: str) -> MarketplaceSyncResult:
    with get_session_with_current_tenant() as db_session:
        record_marketplace_error__no_commit(marketplace_id, error, db_session)
        db_session.commit()
    return MarketplaceSyncResult(status=MarketplaceSyncStatus.FAILED)


def sync_marketplace(marketplace_id: UUID) -> MarketplaceSyncResult:
    """One sync. A failure of GitHub or of the read is recorded in
    last_error and changes no plugin."""
    with get_session_with_current_tenant() as db_session:
        marketplace = get_github_marketplace(marketplace_id, db_session)
        if marketplace is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
        login_user = (
            fetch_user_by_id(db_session, marketplace.login_user_id)
            if marketplace.login_user_id is not None
            else None
        )
        if login_user is None or not login_user.is_active:
            return _record_failure(marketplace_id, LOGIN_GONE_ERROR)
        authorization = github_authorization_for(login_user.id, db_session)
        adapter = marketplace_adapter(marketplace, authorization)
        folder = marketplace_config(marketplace).folder
        login_user_id = login_user.id
        login_email = login_user.email
        db_session.expunge(login_user)

    try:
        read = read_marketplace_repository(adapter, folder)
    except OnyxError as exc:
        if exc.error_code == OnyxErrorCode.NOT_FOUND and authorization is None:
            return _record_failure(
                marketplace_id,
                f"The GitHub connection of {login_email} is gone. Replace the login.",
            )
        return _record_failure(marketplace_id, exc.detail)
    if read.failure is not None or read.name is None:
        return _record_failure(marketplace_id, read.failure or SYNC_FAILED_ERROR)
    entries = read.entries

    with get_session_with_current_tenant() as db_session:
        plan = plan_marketplace_sync(
            entries, list_synced_plugins(marketplace_id, db_session)
        )
    staged = (
        {}
        if plan.needs_confirmation
        else _stage(entries, set(plan.create) | set(plan.add_version))
    )
    file_store = get_default_file_store()
    try:
        with get_session_with_current_tenant() as db_session:
            login = fetch_user_by_id(db_session, login_user_id)
            result = apply_marketplace_sync__no_commit(
                marketplace_id=marketplace_id,
                name=read.name,
                revision=read.revision,
                tree_sha=(read.tree_shas or {}).get(folder or ""),
                entries=entries,
                staged=staged,
                created_by=login,
                db_session=db_session,
            )
            db_session.commit()
    except Exception:
        for content in staged.values():
            delete_bundle_blob(file_store, content.bundle_file_id)
        raise
    delete_files_best_effort(result.cleanup_file_ids, _BUNDLE_CLEANUP)
    if result.affected_user_ids:
        with get_session_with_current_tenant() as db_session:
            push_skills_and_commit(result.affected_user_ids, db_session)
    return result


def sync_request_is_live(sync_requested_at: datetime | None) -> bool:
    """A mark older than the lock timeout has no task left to take it: its
    worker died. The marketplace then counts as not syncing."""
    return sync_requested_at is not None and datetime.now(
        timezone.utc
    ) - sync_requested_at < timedelta(seconds=SYNC_REQUEST_STALE_SECONDS)


def _sync_once(marketplace_id: UUID) -> bool:
    """Take the mark and sync. Returns False when the marketplace is gone."""
    with get_session_with_current_tenant() as db_session:
        take_marketplace_sync_request__no_commit(marketplace_id, db_session)
        db_session.commit()
    try:
        sync_marketplace(marketplace_id)
    except OnyxError as exc:
        if exc.error_code == OnyxErrorCode.NOT_FOUND:
            return False
        _record_failure(marketplace_id, exc.detail)
        raise
    except Exception:
        _record_failure(marketplace_id, SYNC_FAILED_ERROR)
        raise
    return True


def _sync_requested(marketplace_id: UUID) -> bool:
    with get_session_with_current_tenant() as db_session:
        marketplace = get_github_marketplace(marketplace_id, db_session)
        return marketplace is not None and marketplace.sync_requested_at is not None


def _start_follow_up_sync(marketplace_id: UUID) -> None:
    """Start a new task for a mark that a request set during this run. Each
    pass clears the mark first, so this follows only a newer request."""
    if not _sync_requested(marketplace_id):
        return
    tenant_id = get_current_tenant_id()
    if DISABLE_VECTOR_DB:
        run_in_background(_run_in_tenant, marketplace_id, tenant_id)
        return
    _send_sync_task(marketplace_id, tenant_id)


def run_marketplace_sync(marketplace_id: UUID) -> None:
    """Sync under the marketplace's lock. When the lock is taken, set the
    "sync again" mark for the holder and return. The holder syncs again while
    the mark is set. When it stops for the time budget or an error with the
    mark set, it starts a follow-up task."""
    lock = get_cache_backend().lock(
        _sync_lock_name(marketplace_id), timeout=SYNC_LOCK_TIMEOUT_SECONDS
    )
    deadline = time.monotonic() + SYNC_TIME_BUDGET_SECONDS
    while True:
        if not lock.acquire(blocking=False):
            with get_session_with_current_tenant() as db_session:
                request_marketplace_sync__no_commit(marketplace_id, db_session)
                db_session.commit()
            return
        try:
            exists = _sync_once(marketplace_id)
        except Exception:
            if lock.owned():
                lock.release()
            _start_follow_up_sync(marketplace_id)
            raise
        finally:
            if lock.owned():
                lock.release()
        if not exists or not _sync_requested(marketplace_id):
            return
        if time.monotonic() > deadline:
            _start_follow_up_sync(marketplace_id)
            return


def _run_in_tenant(marketplace_id: UUID, tenant_id: str) -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        run_marketplace_sync(marketplace_id)
    except Exception:
        logger.exception("Marketplace sync failed: %s", marketplace_id)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def enqueue_marketplace_sync(
    marketplace_id: UUID, background_tasks: BackgroundTasks
) -> None:
    """Start a sync after the caller committed. Onyx Lite runs no Celery
    workers, so the API server runs the sync after the response."""
    tenant_id = get_current_tenant_id()
    if DISABLE_VECTOR_DB:
        background_tasks.add_task(_run_in_tenant, marketplace_id, tenant_id)
        return
    _send_sync_task(marketplace_id, tenant_id)


def _send_sync_task(marketplace_id: UUID, tenant_id: str) -> None:
    from onyx.background.celery.versioned_apps.client import app as celery_app

    celery_app.send_task(
        OnyxCeleryTask.SYNC_MARKETPLACE,
        kwargs={"marketplace_id": str(marketplace_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.SANDBOX,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=SYNC_TASK_EXPIRES_SECONDS,
    )
