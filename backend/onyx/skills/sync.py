"""Stage marketplace bundles, commit their rows together, then remove unused files.

S5 must serialize this entire operation, including the read and upload phases.
S8 owns confirmation of the retirement guard; this service preserves its result.
"""

from uuid import UUID, uuid4

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.marketplace import (
    fetch_marketplace_sync_state,
    reconcile_marketplace__no_commit,
)
from onyx.db.resource_version import repair_version_metadata
from onyx.db.skill_version import delete_unreferenced_skill_bundles
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.ingest import (
    IngestedBundle,
    prepare_skill_bundle,
    save_skill_bundle_bytes,
)
from onyx.skills.marketplace.models import ReconciliationResult
from onyx.skills.marketplace.provider import get_marketplace_adapter
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    ReadySkill,
    UnsupportedPlugin,
)
from onyx.skills.marketplace.reader import read_marketplace_archive
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _cleanup(file_ids: set[str]) -> None:
    try:
        with get_session_with_current_tenant() as db_session:
            delete_unreferenced_skill_bundles(list(file_ids), db_session)
    except Exception:
        logger.warning(
            "Marketplace bundle cleanup deferred to orphan sweep", exc_info=True
        )


def sync_marketplace(
    marketplace_id: UUID, tenant_id: str
) -> ReconciliationResult | None:
    """Run in the target tenant context. Return None for a healthy unchanged source.

    Owns its sessions and commit. Callers must authorize access before invoking.
    Failed commit attempts leave uploads for the aged orphan sweep.
    A stopped worker leaves aged uploads for V3's orphan sweep.
    """
    with get_session_with_current_tenant() as db_session:
        marketplace, current = fetch_marketplace_sync_state(marketplace_id, db_session)
    file_store = get_default_file_store()
    # These versions are detached; verification cannot write during staging.
    recovery_keys = frozenset(
        key
        for key, version in current.items()
        if version is None
        or version.content_digest is None
        or not repair_version_metadata(
            version, file_store, limits=STORED_BUNDLE_LIMITS, verify_bundle=True
        )
    )
    archive = get_marketplace_adapter(marketplace, tenant_id).fetch_if_changed(
        force=bool(recovery_keys)
    )
    if archive is None:
        return None
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
            result = reconcile_marketplace__no_commit(
                marketplace_id,
                read,
                revision=archive.revision,
                staged=staged,
                db_session=db_session,
                created_by_user_id=marketplace.login_user_id,
                recovery_keys=recovery_keys,
            )
            commit_attempted = True
            db_session.commit()
    except Exception:
        if not commit_attempted:
            _cleanup(uploaded)
        raise
    _cleanup(result.cleanup_file_ids)
    return result
