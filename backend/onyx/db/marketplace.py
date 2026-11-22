from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update
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
)
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
from onyx.skills.models import PluginFileEntry, PluginVersionContent
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
    if owner_user_id is not None and db_session.scalar(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.GITHUB,
            Marketplace.owner_user_id.is_(None),
            Marketplace.repository == config.repository,
            Marketplace.folder == (config.folder or ""),
            Marketplace.ref == (config.ref or ""),
        )
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Your organization already gets this marketplace.",
        )
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


def source_added_for(
    config: GitHubMarketplaceConfig, user_id: UUID, db_session: Session
) -> tuple[bool, bool]:
    """Whether the user's personal marketplaces, and the company ones, already
    have this source."""
    owners = db_session.scalars(
        select(Marketplace.owner_user_id).where(
            Marketplace.kind == MarketplaceKind.GITHUB,
            Marketplace.repository == config.repository,
            Marketplace.folder == (config.folder or ""),
            Marketplace.ref == (config.ref or ""),
            or_(
                Marketplace.owner_user_id == user_id,
                Marketplace.owner_user_id.is_(None),
            ),
        )
    ).all()
    return user_id in owners, None in owners


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
    owner_user_id: UUID, db_session: Session
) -> list[tuple[Marketplace, int]]:
    """The company marketplaces and the user's personal ones."""
    plugin_count = (
        select(func.count(Plugin.id))
        .where(Plugin.marketplace_id == Marketplace.id)
        .correlate(Marketplace)
        .scalar_subquery()
    )
    owner_filter = (Marketplace.owner_user_id == owner_user_id) | (
        Marketplace.owner_user_id.is_(None)
    )
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
    # Plugin locks in id order, as bulk sharing takes them, so the two cannot
    # deadlock.
    for plugin_id in sorted({*plan.delete_plugin_ids, *plan.add_version.values()}):
        lock_plugin(plugin_id, db_session)
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
    # A new plugin starts off for everyone who has not chosen, as in Claude;
    # the owner of a personal marketplace turns plugins on one at a time.
    created = [
        create_synced_plugin__no_commit(
            marketplace, key, staged[key], created_by, db_session
        )
        for key in plan.create
    ]
    affected = set(before)
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
