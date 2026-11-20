import time
from collections.abc import Callable
from typing import Final
from uuid import UUID

from fastapi import BackgroundTasks

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock, CacheLockLostError
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
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.integrations.github_auth import github_authorization_for
from onyx.skills.ingest import delete_bundle_blob, store_version_content
from onyx.skills.ingest_from_github import RepositoryArchive, read_repository_archive
from onyx.skills.marketplace.compare import plan_marketplace_sync
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CompleteMarketplace,
    GitHubRepoSource,
    MarketplaceRead,
    MarketplaceReasonCode,
    MarketplaceSyncResult,
    MarketplaceSyncStatus,
    ReadyPlugin,
    RemotePlugin,
    UnsupportedPlugin,
)
from onyx.skills.marketplace.provider import (
    REMOTE_REPOSITORY_MAX_COUNT,
    REMOTE_REPOSITORY_MAX_COUNT_WITH_LOGIN,
    GitHubMarketplaceAdapter,
    marketplace_config,
)
from onyx.skills.marketplace.reader import (
    BundleBudget,
    build_entry_bundle,
    read_marketplace,
)
from onyx.skills.models import PluginVersionContent
from onyx.skills.push import push_skills_and_commit
from onyx.utils.github import GITHUB_REPOSITORY_NOT_FOUND
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

# A short lease that each sync step renews, so a dead worker frees it soon.
SYNC_LOCK_TIMEOUT_SECONDS: Final = 5 * 60
# Celery thread pools do not enforce time limits; the sync stops itself.
SYNC_MAX_SECONDS: Final = 30 * 60
SYNC_TASK_EXPIRES_SECONDS: Final = 60 * 60
LOGIN_GONE_ERROR: Final = (
    "The login user of this marketplace is gone. Replace the login."
)
SYNC_FAILED_ERROR: Final = "The sync failed. Try again."
_BUNDLE_CLEANUP = "marketplace bundle cleanup"


Heartbeat = Callable[[], None]


def _no_heartbeat() -> None:
    return None


def _resolve_remote_entries(
    entries: tuple[ReadyPlugin | BlockedPlugin | UnsupportedPlugin | RemotePlugin, ...],
    adapter: GitHubMarketplaceAdapter,
    heartbeat: Heartbeat,
) -> list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin]:
    """Holds the files of one remote repository at a time. Raises ValueError
    when all ready plugins together pass the marketplace limits."""
    budget = BundleBudget()
    by_repository: dict[GitHubRepoSource, list[tuple[int, RemotePlugin]]] = {}
    resolved: dict[int, ReadyPlugin | BlockedPlugin | UnsupportedPlugin] = {}
    for index, entry in enumerate(entries):
        if isinstance(entry, RemotePlugin):
            by_repository.setdefault(
                entry.source.model_copy(update={"path": None}), []
            ).append((index, entry))
            continue
        if isinstance(entry, ReadyPlugin):
            budget.add(entry)
        resolved[index] = entry
    with_login = adapter.authorization is not None
    limit = (
        REMOTE_REPOSITORY_MAX_COUNT_WITH_LOGIN
        if with_login
        else REMOTE_REPOSITORY_MAX_COUNT
    )
    past_limit = BlockedPlugin(
        entry_key="",
        path=None,
        reason=(
            f"Onyx syncs at most {limit} external repositories for one marketplace."
            if with_login
            else f"Connect GitHub to sync more than {limit} external repositories."
        ),
        reason_code=(
            MarketplaceReasonCode.EXTERNAL_REPOSITORY_LIMIT
            if with_login
            else MarketplaceReasonCode.EXTERNAL_REPOSITORY_LIMIT_WITHOUT_LOGIN
        ),
    )
    for count, remote_entries in enumerate(by_repository.values()):
        if count >= limit:
            for index, entry in remote_entries:
                resolved[index] = past_limit.model_copy(
                    update={"entry_key": entry.entry_key}
                )
            continue
        source = remote_entries[0][1].source
        heartbeat()
        files: RepositoryArchive | str
        try:
            files = adapter.fetch_remote(source)
        except OnyxError as exc:
            files = f"{source.owner}/{source.repo}: {exc.detail}"
        for index, entry in remote_entries:
            if isinstance(files, str):
                resolved[index] = BlockedPlugin(
                    entry_key=entry.entry_key, path=None, reason=files
                )
                continue
            result = build_entry_bundle(
                files.files,
                entry.source.path or "",
                entry.entry,
                entry.entry_key,
                files.links,
            )
            if isinstance(result, ReadyPlugin):
                budget.add(result)
            resolved[index] = result
    return [resolved[index] for index in range(len(entries))]


def read_marketplace_repository(
    adapter: GitHubMarketplaceAdapter,
    folder: str | None,
    heartbeat: Heartbeat = _no_heartbeat,
) -> MarketplaceRead:
    revision = adapter.resolve_revision()
    heartbeat()
    archive = adapter.fetch(revision)
    heartbeat()
    repository = read_repository_archive(archive)
    read = read_marketplace(repository.files, folder, repository.links)
    if not isinstance(read, CompleteMarketplace):
        return MarketplaceRead(
            revision=revision, name=None, failure=read.reason, entries=[]
        )
    try:
        entries = _resolve_remote_entries(read.entries, adapter, heartbeat)
    except ValueError as exc:
        return MarketplaceRead(
            revision=revision, name=None, failure=str(exc), entries=[]
        )
    return MarketplaceRead(
        revision=revision, name=read.name, failure=None, entries=entries
    )


def _stage(
    entries: list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin],
    keys: set[str],
    heartbeat: Heartbeat,
) -> dict[str, PluginVersionContent]:
    file_store = get_default_file_store()
    staged: dict[str, PluginVersionContent] = {}
    try:
        for entry in entries:
            if not isinstance(entry, ReadyPlugin) or entry.entry_key not in keys:
                continue
            heartbeat()
            bundle = entry.bundle
            staged[entry.entry_key] = store_version_content(
                bundle.content,
                display_name=f"{bundle.manifest.name}.zip",
                skills=[skill.content for skill in bundle.skills],
                file_store=file_store,
                manifest=bundle.manifest,
                needs=bundle.needs,
            )
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


def sync_marketplace(
    marketplace_id: UUID, lock: CacheLock | None = None
) -> MarketplaceSyncResult:
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
        config = marketplace_config(marketplace)
        adapter = GitHubMarketplaceAdapter(config, authorization)
        folder = config.folder
        login_user_id = login_user.id
        login_email = login_user.email
        db_session.expunge(login_user)

    heartbeat = _lock_heartbeat(marketplace_id, lock)
    try:
        read = read_marketplace_repository(adapter, folder, heartbeat)
    except CacheLockLostError:
        logger.warning("Marketplace sync %s lost its lock", marketplace_id)
        return MarketplaceSyncResult(status=MarketplaceSyncStatus.FAILED)
    except OnyxError as exc:
        if exc.detail == GITHUB_REPOSITORY_NOT_FOUND and authorization is None:
            return _record_failure(
                marketplace_id,
                f"GitHub did not find {config.repository}. If it is private, "
                f"{login_email} must connect GitHub, or another user must "
                "replace the login.",
            )
        return _record_failure(marketplace_id, exc.detail)
    if read.failure is not None or read.name is None:
        return _record_failure(marketplace_id, read.failure or SYNC_FAILED_ERROR)
    entries = read.entries

    with get_session_with_current_tenant() as db_session:
        plan = plan_marketplace_sync(
            entries, list_synced_plugins(marketplace_id, db_session)
        )
    try:
        staged = _stage(entries, set(plan.create) | set(plan.add_version), heartbeat)
    except CacheLockLostError:
        logger.warning("Marketplace sync %s lost its lock", marketplace_id)
        return MarketplaceSyncResult(status=MarketplaceSyncStatus.FAILED)
    file_store = get_default_file_store()
    try:
        try:
            heartbeat()
        except CacheLockLostError:
            # The lock expired during a long read; a newer sync may have written.
            logger.warning("Marketplace sync %s lost its lock", marketplace_id)
            for content in staged.values():
                delete_bundle_blob(file_store, content.bundle_file_id)
            return MarketplaceSyncResult(status=MarketplaceSyncStatus.FAILED)
        with get_session_with_current_tenant() as db_session:
            login = fetch_user_by_id(db_session, login_user_id)
            result = apply_marketplace_sync__no_commit(
                marketplace_id=marketplace_id,
                name=read.name,
                revision=read.revision,
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


def _lock_name(marketplace_id: UUID) -> str:
    return f"marketplace_sync:{marketplace_id}"


def _queued_key(marketplace_id: UUID) -> str:
    return f"marketplace_sync_queued:{marketplace_id}"


def _running_key(marketplace_id: UUID) -> str:
    return f"marketplace_syncing:{marketplace_id}"


def _lock_heartbeat(marketplace_id: UUID, lock: CacheLock | None) -> Heartbeat:
    """Renews the lock and the running key, and raises CacheLockLostError when
    the lock is gone or the sync ran too long."""
    if lock is None:
        return _no_heartbeat
    started = time.monotonic()
    cache = get_cache_backend()

    def heartbeat() -> None:
        if not lock.owned() or time.monotonic() - started > SYNC_MAX_SECONDS:
            raise CacheLockLostError(f"Marketplace sync {marketplace_id} stopped.")
        lock.extend(SYNC_LOCK_TIMEOUT_SECONDS)
        cache.set(_running_key(marketplace_id), b"1", ex=SYNC_LOCK_TIMEOUT_SECONDS)

    return heartbeat


def marketplace_syncing(marketplace_id: UUID) -> bool:
    """Queued or running. The running key lives as long as the lock lease, so
    a dead worker cannot leave a marketplace syncing for long."""
    return bool(
        get_cache_backend().exists_many(
            [_queued_key(marketplace_id), _running_key(marketplace_id)]
        )
    )


def _sync_once(marketplace_id: UUID, lock: CacheLock) -> None:
    try:
        sync_marketplace(marketplace_id, lock)
    except OnyxError as exc:
        if exc.error_code != OnyxErrorCode.NOT_FOUND:
            _record_failure(marketplace_id, exc.detail)
            raise
    except Exception:
        _record_failure(marketplace_id, SYNC_FAILED_ERROR)
        raise


def run_marketplace_sync(marketplace_id: UUID) -> None:
    cache = get_cache_backend()
    lock = cache.lock(_lock_name(marketplace_id), timeout=SYNC_LOCK_TIMEOUT_SECONDS)
    if not lock.acquire(blocking=False):
        return
    try:
        # Running before queued is cleared, so a request in between sees one.
        cache.set(_running_key(marketplace_id), b"1", ex=SYNC_LOCK_TIMEOUT_SECONDS)
        cache.delete(_queued_key(marketplace_id))
        _sync_once(marketplace_id, lock)
    finally:
        # Only the lock owner clears the flag; a newer run may own it now.
        if lock.owned():
            cache.delete(_running_key(marketplace_id))
            lock.release()


def request_marketplace_sync(
    marketplace_id: UUID, background_tasks: BackgroundTasks
) -> None:
    """A request while a sync is queued or running does nothing."""
    if marketplace_syncing(marketplace_id):
        return
    enqueue_marketplace_sync(marketplace_id, background_tasks)


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
    """Onyx Lite runs no Celery workers, so the API server runs the sync."""
    cache = get_cache_backend()
    cache.set(_queued_key(marketplace_id), b"1", ex=SYNC_TASK_EXPIRES_SECONDS)
    tenant_id = get_current_tenant_id()
    if DISABLE_VECTOR_DB:
        background_tasks.add_task(_run_in_tenant, marketplace_id, tenant_id)
        return
    try:
        _send_sync_task(marketplace_id, tenant_id)
    except Exception:
        cache.delete(_queued_key(marketplace_id))
        raise


def _send_sync_task(marketplace_id: UUID, tenant_id: str) -> None:
    from onyx.background.celery.versioned_apps.client import app as celery_app

    celery_app.send_task(
        OnyxCeleryTask.SYNC_MARKETPLACE,
        kwargs={"marketplace_id": str(marketplace_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.SANDBOX,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=SYNC_TASK_EXPIRES_SECONDS,
    )
