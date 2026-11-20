from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind, PluginInstallationPolicy
from onyx.db.models import Marketplace, Plugin, PluginVersion, User
from onyx.db.plugin import (
    add_plugin_version__no_commit,
    create_synced_plugin__no_commit,
    lock_plugin,
)
from onyx.db.plugin_access import affected_user_ids_for_plugins
from onyx.db.skill import (
    delete_skill,
    enable_new_skill_if_name_available__no_commit,
)
from onyx.db.skill_limit import lock_user_skill_preferences
from onyx.db.utils import is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.compare import plan_marketplace_sync
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CurrentSyncedPlugin,
    GitHubMarketplaceConfig,
    MarketplaceEntryResult,
    MarketplaceEntryStatus,
    MarketplaceSyncResult,
    MarketplaceSyncStatus,
    ReadyPlugin,
    UnsupportedPlugin,
)
from onyx.skills.models import PluginFileEntry, PluginNeed, PluginVersionContent
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SOURCE_INDEXES = (
    "uq_plugin_marketplace_personal_source",
    "uq_plugin_marketplace_company_source",
)


def create_github_marketplace__no_commit(
    *,
    name: str,
    config: GitHubMarketplaceConfig,
    owner_user_id: UUID | None,
    login_user_id: UUID,
    default_installation_policy: PluginInstallationPolicy,
    db_session: Session,
) -> Marketplace:
    marketplace = Marketplace(
        kind=MarketplaceKind.GITHUB,
        name=name,
        owner_user_id=owner_user_id,
        login_user_id=login_user_id,
        repository=config.repository,
        folder=config.folder or "",
        ref=config.ref or "",
        default_installation_policy=default_installation_policy,
    )
    try:
        with db_session.begin_nested():
            db_session.add(marketplace)
            db_session.flush()
    except IntegrityError as exc:
        if not any(is_unique_violation(exc, index) for index in _SOURCE_INDEXES):
            raise
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This marketplace is already added."
        ) from exc
    return marketplace


def get_github_marketplace(
    marketplace_id: UUID, db_session: Session
) -> Marketplace | None:
    return db_session.scalar(
        select(Marketplace).where(
            Marketplace.id == marketplace_id,
            Marketplace.kind == MarketplaceKind.GITHUB,
        )
    )


def lock_github_marketplace(
    marketplace_id: UUID, db_session: Session
) -> Marketplace | None:
    return db_session.scalar(
        select(Marketplace)
        .where(
            Marketplace.id == marketplace_id,
            Marketplace.kind == MarketplaceKind.GITHUB,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_github_marketplaces(
    owner_user_id: UUID, include_company: bool, db_session: Session
) -> list[tuple[Marketplace, int]]:
    plugin_count = (
        select(func.count(Plugin.id))
        .where(Plugin.marketplace_id == Marketplace.id)
        .correlate(Marketplace)
        .scalar_subquery()
    )
    owner_filter = Marketplace.owner_user_id == owner_user_id
    if include_company:
        owner_filter = owner_filter | Marketplace.owner_user_id.is_(None)
    return [
        (marketplace, count)
        for marketplace, count in db_session.execute(
            select(Marketplace, plugin_count)
            .where(Marketplace.kind == MarketplaceKind.GITHUB, owner_filter)
            .order_by(Marketplace.created_at, Marketplace.id)
        ).tuples()
    ]


def list_synced_plugins(
    marketplace_id: UUID, db_session: Session
) -> list[CurrentSyncedPlugin]:
    return [
        CurrentSyncedPlugin(
            plugin_id=plugin_id,
            name=name,
            file_manifest=(
                [PluginFileEntry.model_validate(item) for item in manifest]
                if manifest is not None
                else None
            ),
        )
        for plugin_id, name, manifest in db_session.execute(
            select(Plugin.id, Plugin.name, PluginVersion.file_manifest)
            .join(PluginVersion, PluginVersion.id == Plugin.current_version_id)
            .where(Plugin.marketplace_id == marketplace_id)
            .order_by(Plugin.name)
        ).tuples()
    ]


def list_marketplace_plugins(marketplace_id: UUID, db_session: Session) -> list[Plugin]:
    return list(
        db_session.scalars(
            select(Plugin)
            .where(Plugin.marketplace_id == marketplace_id)
            .order_by(Plugin.id)
        )
    )


def record_marketplace_error__no_commit(
    marketplace_id: UUID, error: str, db_session: Session
) -> None:
    db_session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .values(last_error=error)
    )


def _write_sync_state(
    marketplace: Marketplace,
    *,
    name: str,
    revision: str,
    results: Sequence[MarketplaceEntryResult],
) -> None:
    marketplace.name = name
    marketplace.last_synced_revision = revision
    marketplace.last_synced_at = datetime.now(timezone.utc)
    marketplace.last_sync_result = [
        result.model_dump(mode="json") for result in results
    ]
    marketplace.last_error = None


def _turn_on_for_owner__no_commit(
    plugin: Plugin, owner_user_id: UUID, db_session: Session
) -> bool:
    try:
        with db_session.begin_nested():
            return enable_new_skill_if_name_available__no_commit(
                plugin, owner_user_id, db_session
            )
    except OnyxError as exc:
        if exc.error_code != OnyxErrorCode.SKILL_LIMIT_EXCEEDED:
            raise
        logger.info("Synced plugin %s stays off: skill limit", plugin.id)
        return False


def apply_marketplace_sync__no_commit(
    *,
    marketplace_id: UUID,
    name: str,
    revision: str,
    entries: Sequence[ReadyPlugin | BlockedPlugin | UnsupportedPlugin],
    staged: Mapping[str, PluginVersionContent],
    created_by: User | None,
    db_session: Session,
) -> MarketplaceSyncResult:
    marketplace = get_github_marketplace(marketplace_id, db_session)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    owner_user_id = marketplace.owner_user_id
    # The owner's lock first, the order of skill toggles and saves.
    if owner_user_id is not None:
        lock_user_skill_preferences(owner_user_id, db_session)
    marketplace = lock_github_marketplace(marketplace_id, db_session)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    current = list_synced_plugins(marketplace_id, db_session)
    plan = plan_marketplace_sync(entries, current)
    blocked = [
        result.key
        for result in plan.results
        if result.status != MarketplaceEntryStatus.OK
    ]
    needed = set(plan.create) | set(plan.add_version)
    if not needed <= staged.keys():
        raise RuntimeError("Bug: a marketplace change has no staged bundle.")

    kept_ids = [plugin.plugin_id for plugin in current]
    before = affected_user_ids_for_plugins(kept_ids, db_session)
    cleanup = [item.bundle_file_id for key, item in staged.items() if key not in needed]
    for plugin_id in plan.delete_plugin_ids:
        plugin = lock_plugin(plugin_id, db_session)
        if plugin is not None:
            cleanup.extend(delete_skill(plugin, db_session))
    versioned: list[UUID] = []
    for key, plugin_id in sorted(plan.add_version.items()):
        plugin = lock_plugin(plugin_id, db_session)
        if plugin is None:
            raise RuntimeError("Bug: a synced plugin went away under the lock.")
        add_plugin_version__no_commit(
            plugin=plugin,
            content=staged[key],
            base_version_id=None,
            created_by=created_by,
            skip_if_unchanged=False,
            db_session=db_session,
        )
        if owner_user_id is None:
            plugin.published_version_id = plugin.current_version_id
        versioned.append(plugin.id)
    created: list[Plugin] = []
    turned_on_needs: list[PluginNeed] = []
    affected = set(before)
    for key in plan.create:
        plugin = create_synced_plugin__no_commit(
            marketplace, key, staged[key], created_by, db_session
        )
        created.append(plugin)
        if owner_user_id is not None and _turn_on_for_owner__no_commit(
            plugin, owner_user_id, db_session
        ):
            affected.add(owner_user_id)
            turned_on_needs.extend(staged[key].needs or [])
    _write_sync_state(
        marketplace,
        name=name,
        revision=revision,
        results=plan.results,
    )
    db_session.flush()
    affected |= affected_user_ids_for_plugins(
        [*kept_ids, *(plugin.id for plugin in created)], db_session
    )
    return MarketplaceSyncResult(
        status=MarketplaceSyncStatus.APPLIED,
        created=[plugin.id for plugin in created],
        versioned=versioned,
        deleted=plan.delete_plugin_ids,
        blocked=blocked,
        cleanup_file_ids=sorted(cleanup),
        affected_user_ids=affected,
        turned_on_needs=turned_on_needs,
    )


def _delete_plugins__no_commit(
    plugin_ids: Sequence[UUID], db_session: Session
) -> tuple[set[UUID], list[str]]:
    affected = affected_user_ids_for_plugins(plugin_ids, db_session)
    file_ids: list[str] = []
    for plugin_id in sorted(plugin_ids):
        plugin = lock_plugin(plugin_id, db_session)
        if plugin is not None:
            file_ids.extend(delete_skill(plugin, db_session))
    return affected, file_ids


def delete_github_marketplace__no_commit(
    marketplace_id: UUID, db_session: Session
) -> tuple[set[UUID], list[str]]:
    marketplace = lock_github_marketplace(marketplace_id, db_session)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    affected, file_ids = _delete_plugins__no_commit(
        [plugin.id for plugin in list_marketplace_plugins(marketplace_id, db_session)],
        db_session,
    )
    db_session.delete(marketplace)
    db_session.flush()
    return affected, file_ids


def replace_marketplace_login__no_commit(
    marketplace_id: UUID, login_user_id: UUID, db_session: Session
) -> Marketplace:
    marketplace = lock_github_marketplace(marketplace_id, db_session)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    marketplace.login_user_id = login_user_id
    marketplace.last_error = None
    db_session.flush()
    return marketplace
