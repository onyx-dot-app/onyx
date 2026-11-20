"""DB operations for GitHub marketplaces and their sync.

A sync stages its bundles first, then ``apply_marketplace_sync__no_commit``
writes every change of one read in the caller's transaction, under the
marketplace row lock. Functions here flush and never commit.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
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
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.compare import plan_marketplace_sync
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CurrentSyncedPlugin,
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


def create_github_marketplace__no_commit(
    *,
    name: str,
    provider_config: dict[str, Any],
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
        provider_config=provider_config,
        default_installation_policy=default_installation_policy,
    )
    db_session.add(marketplace)
    db_session.flush()
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


def find_github_marketplace(
    owner_user_id: UUID | None,
    provider_config: dict[str, Any],
    db_session: Session,
) -> Marketplace | None:
    """The marketplace of the same owner (None: the company) that reads the
    same repository, folder and ref."""
    return db_session.scalar(
        select(Marketplace)
        .where(
            Marketplace.kind == MarketplaceKind.GITHUB,
            Marketplace.owner_user_id.is_(None)
            if owner_user_id is None
            else Marketplace.owner_user_id == owner_user_id,
            Marketplace.provider_config == provider_config,
        )
        .limit(1)
    )


def list_github_marketplaces(
    owner_user_id: UUID, include_company: bool, db_session: Session
) -> list[tuple[Marketplace, int]]:
    """The user's personal marketplaces, and the company ones when
    ``include_company`` is set, each with its plugin count."""
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


def list_personal_marketplaces(
    owner_user_id: UUID, db_session: Session
) -> list[Marketplace]:
    return list(
        db_session.scalars(
            select(Marketplace)
            .where(
                Marketplace.kind == MarketplaceKind.GITHUB,
                Marketplace.owner_user_id == owner_user_id,
            )
            .order_by(Marketplace.name, Marketplace.id)
        )
    )


def list_synced_plugins(
    marketplace_id: UUID, db_session: Session
) -> list[CurrentSyncedPlugin]:
    return [
        CurrentSyncedPlugin(
            plugin_id=plugin_id,
            entry_key=entry_key,
            name=name,
            file_manifest=(
                [PluginFileEntry.model_validate(item) for item in manifest]
                if manifest is not None
                else None
            ),
        )
        for plugin_id, entry_key, name, manifest in db_session.execute(
            select(
                Plugin.id,
                Plugin.marketplace_entry_key,
                Plugin.name,
                PluginVersion.file_manifest,
            )
            .join(PluginVersion, PluginVersion.id == Plugin.current_version_id)
            .where(
                Plugin.marketplace_id == marketplace_id,
                Plugin.marketplace_entry_key.is_not(None),
            )
            .order_by(Plugin.marketplace_entry_key)
        ).tuples()
        if entry_key is not None
    ]


def list_marketplace_plugins(marketplace_id: UUID, db_session: Session) -> list[Plugin]:
    return list(
        db_session.scalars(
            select(Plugin)
            .where(Plugin.marketplace_id == marketplace_id)
            .order_by(Plugin.id)
        )
    )


def request_marketplace_sync__no_commit(
    marketplace_id: UUID, db_session: Session
) -> None:
    db_session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .values(sync_requested_at=func.now())
    )


def take_marketplace_sync_request__no_commit(
    marketplace_id: UUID, db_session: Session
) -> bool:
    """Clear the "sync again" mark and return whether it was set."""
    return (
        db_session.execute(
            update(Marketplace)
            .where(
                Marketplace.id == marketplace_id,
                Marketplace.sync_requested_at.is_not(None),
            )
            .values(sync_requested_at=None)
            .returning(Marketplace.id)
        ).first()
        is not None
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
    tree_sha: str | None,
    results: Sequence[MarketplaceEntryResult],
) -> None:
    marketplace.name = name
    marketplace.last_synced_revision = revision
    marketplace.last_synced_tree_sha = tree_sha
    marketplace.last_synced_at = datetime.now(timezone.utc)
    marketplace.last_sync_result = [
        result.model_dump(mode="json") for result in results
    ]
    marketplace.last_error = None
    marketplace.pending_delete_revision = None


def _turn_on_for_owner__no_commit(
    plugin: Plugin, owner_user_id: UUID, db_session: Session
) -> bool:
    """A plugin that would put the owner past the skill limit stays off."""
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
    tree_sha: str | None,
    entries: Sequence[ReadyPlugin | BlockedPlugin | UnsupportedPlugin],
    staged: Mapping[str, PluginVersionContent],
    created_by: User | None,
    db_session: Session,
) -> MarketplaceSyncResult:
    """Write one complete read. Compares again under the marketplace lock, so
    the plan fits the rows it writes. ``staged`` holds the stored content of
    each entry to create or version."""
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
    if plan.needs_confirmation:
        marketplace.pending_delete_revision = revision
        marketplace.last_sync_result = [
            result.model_dump(mode="json") for result in plan.results
        ]
        marketplace.last_error = None
        db_session.flush()
        return MarketplaceSyncResult(
            status=MarketplaceSyncStatus.NEEDS_CONFIRMATION,
            blocked=blocked,
            cleanup_file_ids=sorted(item.bundle_file_id for item in staged.values()),
        )
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
    created: list[Plugin] = [
        create_synced_plugin__no_commit(
            marketplace, key, staged[key], created_by, db_session
        )
        for key in plan.create
    ]
    affected = set(before)
    if owner_user_id is not None:
        turned_on = [
            _turn_on_for_owner__no_commit(plugin, owner_user_id, db_session)
            for plugin in created
        ]
        if any(turned_on):
            affected.add(owner_user_id)
    _write_sync_state(
        marketplace,
        name=name,
        revision=revision,
        tree_sha=tree_sha,
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


def pending_delete_plugins(
    marketplace: Marketplace, db_session: Session
) -> list[CurrentSyncedPlugin]:
    """The plugins a sync waiting for confirmation would delete: those whose
    entry the last read did not hold."""
    if marketplace.pending_delete_revision is None:
        return []
    keys = {
        MarketplaceEntryResult.model_validate(item).key
        for item in marketplace.last_sync_result or []
    }
    return [
        plugin
        for plugin in list_synced_plugins(marketplace.id, db_session)
        if plugin.entry_key not in keys
    ]


def confirm_marketplace_deletes__no_commit(
    marketplace_id: UUID, revision: str, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete the plugins a sync held back at ``revision``. The next sync
    then writes the rest of that read. Returns the affected users and the
    bundle files to delete after commit."""
    marketplace = lock_github_marketplace(marketplace_id, db_session)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    if (
        marketplace.pending_delete_revision is None
        or marketplace.pending_delete_revision != revision
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "The marketplace changed since you looked. Reload it, then confirm again.",
        )
    plugin_ids = [
        plugin.plugin_id for plugin in pending_delete_plugins(marketplace, db_session)
    ]
    marketplace.pending_delete_revision = None
    db_session.flush()
    return _delete_plugins__no_commit(plugin_ids, db_session)


def delete_github_marketplace__no_commit(
    marketplace_id: UUID, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete a marketplace and its plugins. Returns the affected users and
    the bundle files to delete after commit."""
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
