from collections.abc import Callable
from typing import Final
from uuid import UUID

from fastapi import BackgroundTasks

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
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
from onyx.integrations.plugin_needs import turn_on_needed_integrations__no_commit
from onyx.integrations.service import reload_craft_sessions
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
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

# Short so a killed worker frees the marketplace soon; a running sync extends it
# between steps.
SYNC_LOCK_TIMEOUT_SECONDS: Final = 5 * 60
SYNC_TASK_EXPIRES_SECONDS: Final = 60 * 60
LOGIN_GONE_ERROR: Final = (
    "The login user of this marketplace is gone. Replace the login."
)
SYNC_FAILED_ERROR: Final = "The sync failed. Try again."
_BUNDLE_CLEANUP = "marketplace bundle cleanup"


def _resolve_remote_entries(
    entries: tuple[ReadyPlugin | BlockedPlugin | UnsupportedPlugin | RemotePlugin, ...],
    adapter: GitHubMarketplaceAdapter,
    keep_alive: Callable[[], None],
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
    for count, remote_entries in enumerate(by_repository.values()):
        source = remote_entries[0][1].source
        files: dict[str, bytes] | str
        if count >= REMOTE_REPOSITORY_MAX_COUNT:
            files = (
                f"The marketplace names more than {REMOTE_REPOSITORY_MAX_COUNT} "
                "other repositories."
            )
        else:
            keep_alive()
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
                files, entry.source.path or "", entry.entry, entry.entry_key
            )
            if isinstance(result, ReadyPlugin):
                budget.add(result)
            resolved[index] = result
    return [resolved[index] for index in range(len(entries))]


def read_marketplace_repository(
    adapter: GitHubMarketplaceAdapter,
    folder: str | None,
    keep_alive: Callable[[], None] = lambda: None,
) -> MarketplaceRead:
    revision = adapter.resolve_revision()
    keep_alive()
    read = read_marketplace(read_repository_archive(adapter.fetch(revision)), folder)
    keep_alive()
    if not isinstance(read, CompleteMarketplace):
        return MarketplaceRead(
            revision=revision, name=None, failure=read.reason, entries=[]
        )
    try:
        entries = _resolve_remote_entries(read.entries, adapter, keep_alive)
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
) -> dict[str, PluginVersionContent]:
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
    def keep_alive() -> None:
        if lock is not None and lock.owned():
            lock.extend(SYNC_LOCK_TIMEOUT_SECONDS)
            get_cache_backend().set(
                _syncing_key(marketplace_id), b"1", ex=SYNC_LOCK_TIMEOUT_SECONDS
            )

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
        owner_user_id = marketplace.owner_user_id
        login_user_id = login_user.id
        login_email = login_user.email
        db_session.expunge(login_user)

    try:
        read = read_marketplace_repository(adapter, folder, keep_alive)
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
    keep_alive()
    staged = _stage(entries, set(plan.create) | set(plan.add_version))
    keep_alive()
    file_store = get_default_file_store()
    if lock is not None and not lock.owned():
        # The lock expired during a long read; a newer sync may have written.
        logger.warning("Marketplace sync %s lost its lock", marketplace_id)
        for content in staged.values():
            delete_bundle_blob(file_store, content.bundle_file_id)
        return MarketplaceSyncResult(status=MarketplaceSyncStatus.FAILED)
    try:
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
            owner = (
                fetch_user_by_id(db_session, owner_user_id)
                if owner_user_id is not None and result.turned_on_needs
                else None
            )
            integrations_changed = (
                owner is not None
                and turn_on_needed_integrations__no_commit(
                    owner, result.turned_on_needs, db_session
                )
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
    if integrations_changed and owner_user_id is not None:
        with get_session_with_current_tenant() as db_session:
            reload_craft_sessions({owner_user_id}, db_session)
    return result


def _syncing_key(marketplace_id: UUID) -> str:
    return f"marketplace_syncing:{marketplace_id}"


def marketplace_syncing(marketplace_id: UUID) -> bool:
    """The key expires, so a dead worker cannot leave a marketplace syncing."""
    return get_cache_backend().exists(_syncing_key(marketplace_id))


def run_marketplace_sync(marketplace_id: UUID) -> None:
    cache = get_cache_backend()
    lock = cache.lock(
        f"marketplace_sync:{marketplace_id}", timeout=SYNC_LOCK_TIMEOUT_SECONDS
    )
    if not lock.acquire(blocking=False):
        return
    cache.set(_syncing_key(marketplace_id), b"1", ex=SYNC_LOCK_TIMEOUT_SECONDS)
    try:
        sync_marketplace(marketplace_id, lock)
    except OnyxError as exc:
        if exc.error_code != OnyxErrorCode.NOT_FOUND:
            _record_failure(marketplace_id, exc.detail)
            raise
    except Exception:
        _record_failure(marketplace_id, SYNC_FAILED_ERROR)
        raise
    finally:
        # A sync that lost its lock leaves the key to the newer sync, or to
        # its expiry.
        if lock.owned():
            cache.delete(_syncing_key(marketplace_id))
            lock.release()


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
    cache.set(_syncing_key(marketplace_id), b"1", ex=SYNC_TASK_EXPIRES_SECONDS)
    tenant_id = get_current_tenant_id()
    if DISABLE_VECTOR_DB:
        background_tasks.add_task(_run_in_tenant, marketplace_id, tenant_id)
        return
    try:
        _send_sync_task(marketplace_id, tenant_id)
    except Exception:
        cache.delete(_syncing_key(marketplace_id))
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
