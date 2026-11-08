"""Stage marketplace bundles, commit their rows together, then remove unused files.

A renewable database lease serializes reads, uploads and publication.
S8 owns confirmation of the retirement guard; this service preserves its result.
"""

from uuid import UUID, uuid4

from onyx.background.celery.tasks.shared.lease_heartbeat import LeaseHeartbeat
from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_tenant,
)
from onyx.db.marketplace import (
    fetch_marketplace_sync_state,
    reconcile_marketplace__no_commit,
)
from onyx.db.marketplace_sync import (
    LEASE_SECONDS,
    MAX_RUN_SECONDS,
    SYNC_FAILED,
    MarketplaceSyncLeaseLost,
    claim_marketplace_sync,
    fence_marketplace_sync,
    finish_marketplace_sync,
    finish_marketplace_sync__no_commit,
    renew_marketplace_sync,
    request_marketplace_sync,
)
from onyx.db.models import SkillVersion
from onyx.db.resource_version import repair_version_metadata
from onyx.db.skill_version import delete_unreferenced_skill_bundles
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.ingest import (
    IngestedBundle,
    prepare_skill_bundle,
    save_skill_bundle_bytes,
)
from onyx.skills.marketplace.models import (
    MARKETPLACE_LOGIN_ERROR,
    MarketplaceSyncStatus,
    ReconciliationResult,
)
from onyx.skills.marketplace.provider import get_marketplace_adapter
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    ReadySkill,
    UnsupportedPlugin,
)
from onyx.skills.marketplace.reader import read_marketplace_archive
from onyx.skills.push import push_skills_for_users
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _cleanup(file_ids: set[str]) -> None:
    try:
        with get_session_with_current_tenant() as db_session:
            delete_unreferenced_skill_bundles(list(file_ids), db_session)
    except Exception:
        logger.warning(
            "Marketplace bundle cleanup deferred to orphan sweep", exc_info=True
        )


def _bundle_available(version: SkillVersion, file_store: FileStore) -> bool:
    if version.bundle_file_id is None:
        return False
    try:
        size = file_store.get_file_size(version.bundle_file_id)
    except FileNotFoundError:
        return False
    if size is None:
        return repair_version_metadata(
            version, file_store, limits=STORED_BUNDLE_LIMITS, verify_bundle=True
        )
    return 0 < size <= STORED_BUNDLE_LIMITS.max_stored_bytes


def _sync_marketplace(
    marketplace_id: UUID, tenant_id: str, owner: UUID
) -> tuple[ReconciliationResult | None, bool]:
    """Return the result and pending work after committing completion with publication.

    Owns its sessions and commit. Callers must authorize access before invoking.
    Failed commit attempts leave uploads for the aged orphan sweep.
    A stopped worker leaves aged uploads for V3's orphan sweep.
    """
    with get_session_with_current_tenant() as db_session:
        marketplace, current = fetch_marketplace_sync_state(marketplace_id, db_session)
    file_store = get_default_file_store()
    # Probe object metadata on unchanged runs; decode bundles on source changes.
    recovery_keys = frozenset(
        key
        for key, version in current.items()
        if version is None
        or version.content_digest is None
        or not _bundle_available(version, file_store)
    )
    archive = get_marketplace_adapter(marketplace, tenant_id).fetch_if_changed(
        force=any(
            key not in marketplace.blocked_entries
            and key.split("/", 1)[0] not in marketplace.blocked_entries
            for key in recovery_keys
        )
    )
    if archive is None:
        with get_session_with_current_tenant() as db_session:
            pending = finish_marketplace_sync__no_commit(
                marketplace_id,
                owner,
                db_session,
                status=MarketplaceSyncStatus.APPLIED,
                resolved_revision=marketplace.last_synced_revision,
            )
            db_session.commit()
        return None, pending
    if archive.revision != marketplace.last_synced_revision:
        recovery_keys |= frozenset(
            key
            for key, version in current.items()
            if key not in recovery_keys
            and version is not None
            and not repair_version_metadata(
                version, file_store, limits=STORED_BUNDLE_LIMITS, verify_bundle=True
            )
        )
    read = read_marketplace_archive(archive.archive_bytes, folder=archive.folder)
    staged: dict[str, IngestedBundle] = {}
    uploaded: set[str] = set()
    commit_attempted = False
    try:
        if isinstance(read, CompleteMarketplace):
            entries: list[ReadySkill | BlockedSkill | UnsupportedPlugin] = []
            for entry in read.entries:
                if not isinstance(entry, ReadySkill):
                    entries.append(entry)
                    continue
                try:
                    prepared = prepare_skill_bundle(
                        entry.bundle_bytes,
                        None,
                        expected_name=entry.path.rsplit("/", 1)[-1],
                    )
                except (ValueError, OnyxError) as exc:
                    entries.append(
                        BlockedSkill(
                            entry_key=entry.entry_key, path=entry.path, reason=str(exc)
                        )
                    )
                    continue
                entries.append(entry)
                version = current.get(entry.entry_key)
                if (
                    entry.entry_key not in recovery_keys
                    and version is not None
                    and version.content_digest == entry.content_digest
                ):
                    continue
                file_id = str(uuid4())
                uploaded.add(file_id)
                save_skill_bundle_bytes(
                    prepared.content,
                    display_name=f"{prepared.canonical_name}.zip",
                    file_store=file_store,
                    file_id=file_id,
                )
                staged[entry.entry_key] = IngestedBundle(
                    prepared.canonical_name,
                    file_id,
                    prepared.bundle_sha256,
                    prepared.description,
                    prepared.metadata,
                )
            read = CompleteMarketplace(entries=entries)
        with get_session_with_current_tenant() as db_session:
            locked = fence_marketplace_sync(marketplace_id, owner, db_session)
            if (
                locked.login_user_id is None
                or locked.login_user_id != marketplace.login_user_id
            ):
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, MARKETPLACE_LOGIN_ERROR)
            result = reconcile_marketplace__no_commit(
                marketplace_id,
                read,
                revision=archive.revision,
                staged=staged,
                db_session=db_session,
                created_by_user_id=marketplace.login_user_id,
                recovery_keys=recovery_keys,
            )
            status = MarketplaceSyncStatus(result.status)
            pending = finish_marketplace_sync__no_commit(
                marketplace_id,
                owner,
                db_session,
                status=status,
                error="needs confirmation"
                if status == MarketplaceSyncStatus.NEEDS_CONFIRMATION
                else SYNC_FAILED
                if status == MarketplaceSyncStatus.FAILED
                else None,
                resolved_revision=archive.revision,
            )
            commit_attempted = True
            db_session.commit()
    except Exception:
        if not commit_attempted:
            _cleanup(uploaded)
        raise
    _cleanup(result.cleanup_file_ids)
    if result.affected_user_ids:
        try:
            with get_session_with_current_tenant() as db_session:
                push_skills_for_users(result.affected_user_ids, db_session)
                db_session.commit()
        except Exception:
            logger.warning(
                "Marketplace sandbox push failed after publication", exc_info=True
            )
    if (
        archive.revision == marketplace.last_synced_revision
        and result.status == "applied"
        and not result.changed_skill_ids
        and not result.retired_skill_ids
    ):
        return None, pending
    return result, pending


def sync_marketplace(
    marketplace_id: UUID, tenant_id: str, *, request_work: bool = True
) -> ReconciliationResult | None:
    """Serialize the full operation. Busy callers durably request another pass.

    Background workers use request_work=False: duplicate deliveries must not create
    new work. After two passes, recovery dispatches any remaining requested work.
    """
    context = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    result: ReconciliationResult | None = None
    try:
        if request_work:
            maybe_mark_tenant_active(tenant_id, caller="marketplace_sync")
            with get_session_with_tenant(tenant_id=tenant_id) as session:
                request_marketplace_sync(marketplace_id, session)
        for _ in range(2):
            with get_session_with_tenant(tenant_id=tenant_id) as session:
                owner = claim_marketplace_sync(marketplace_id, session)
            if owner is None:
                break
            maybe_mark_tenant_active(tenant_id, caller="marketplace_sync")

            def renew(owner: UUID = owner) -> bool:
                with get_session_with_tenant(tenant_id=tenant_id) as session:
                    return renew_marketplace_sync(marketplace_id, owner, session)

            with LeaseHeartbeat(
                f"marketplace:{marketplace_id}",
                renew,
                interval=10,
                max_silence=LEASE_SECONDS / 2,
                max_duration=MAX_RUN_SECONDS,
            ):
                try:
                    result, pending = _sync_marketplace(
                        marketplace_id, tenant_id, owner
                    )
                except MarketplaceSyncLeaseLost:
                    raise
                except Exception as exc:
                    error = (
                        MARKETPLACE_LOGIN_ERROR
                        if isinstance(exc, OnyxError)
                        and exc.detail == MARKETPLACE_LOGIN_ERROR
                        else SYNC_FAILED
                    )
                    try:
                        with get_session_with_tenant(tenant_id=tenant_id) as session:
                            finish_marketplace_sync(
                                marketplace_id,
                                owner,
                                session,
                                status=MarketplaceSyncStatus.FAILED,
                                error=error,
                                retry=isinstance(exc, OnyxError)
                                and exc.error_code
                                in {
                                    OnyxErrorCode.BAD_GATEWAY,
                                    OnyxErrorCode.GATEWAY_TIMEOUT,
                                    OnyxErrorCode.RATE_LIMITED,
                                    OnyxErrorCode.SERVICE_UNAVAILABLE,
                                },
                            )
                        maybe_mark_tenant_active(tenant_id, caller="marketplace_sync")
                    except MarketplaceSyncLeaseLost:
                        logger.warning(
                            "Sync failure could not update released ownership"
                        )
                    raise
                if not pending:
                    break
        return result
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context)
