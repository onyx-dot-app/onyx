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
    claim_marketplace_sync_request__no_commit,
    finish_marketplace_sync_request__no_commit,
    get_github_marketplace,
    list_synced_plugins,
    record_marketplace_error__no_commit,
    request_marketplace_sync__no_commit,
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
    MarketplaceProviderAdapter,
    marketplace_adapter,
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
from onyx.utils.threadpool_concurrency import run_in_background
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

SYNC_LOCK_TIMEOUT_SECONDS: Final = 30 * 60
SYNC_TIME_BUDGET_SECONDS: Final = 20 * 60
SYNC_TASK_EXPIRES_SECONDS: Final = 60 * 60
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
    adapter: MarketplaceProviderAdapter, folder: str | None
) -> MarketplaceRead:
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
    try:
        entries = _resolve_remote_entries(read.entries, adapter)
    except ValueError as exc:
        return MarketplaceRead(
            revision=revision,
            tree_shas=archive.tree_shas,
            name=None,
            failure=str(exc),
            entries=[],
        )
    return MarketplaceRead(
        revision=revision,
        tree_shas=archive.tree_shas,
        name=read.name,
        failure=None,
        entries=entries,
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
        owner_user_id = marketplace.owner_user_id
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


def sync_request_is_live(sync_requested_at: datetime | None) -> bool:
    return sync_requested_at is not None and datetime.now(
        timezone.utc
    ) - sync_requested_at < timedelta(seconds=SYNC_REQUEST_STALE_SECONDS)


def _sync_once(marketplace_id: UUID) -> bool:
    with get_session_with_current_tenant() as db_session:
        claimed_at = claim_marketplace_sync_request__no_commit(
            marketplace_id, db_session
        )
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
    finally:
        if claimed_at is not None:
            with get_session_with_current_tenant() as db_session:
                finish_marketplace_sync_request__no_commit(
                    marketplace_id, claimed_at, db_session
                )
                db_session.commit()
    return True


def _sync_requested(marketplace_id: UUID) -> bool:
    with get_session_with_current_tenant() as db_session:
        marketplace = get_github_marketplace(marketplace_id, db_session)
        return marketplace is not None and marketplace.sync_requested_at is not None


def _start_follow_up_sync(marketplace_id: UUID) -> None:
    if not _sync_requested(marketplace_id):
        return
    tenant_id = get_current_tenant_id()
    if DISABLE_VECTOR_DB:
        run_in_background(_run_in_tenant, marketplace_id, tenant_id)
        return
    _send_sync_task(marketplace_id, tenant_id)


def run_marketplace_sync(marketplace_id: UUID) -> None:
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
    """Onyx Lite runs no Celery workers, so the API server runs the sync."""
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
