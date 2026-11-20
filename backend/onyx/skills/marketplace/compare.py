from collections.abc import Sequence
from uuid import UUID

from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CurrentSyncedPlugin,
    MarketplaceEntryResult,
    MarketplaceEntryStatus,
    ReadyPlugin,
    SyncPlan,
    UnsupportedPlugin,
)


def entry_result(
    entry: ReadyPlugin | BlockedPlugin | UnsupportedPlugin,
) -> MarketplaceEntryResult:
    if isinstance(entry, ReadyPlugin):
        return MarketplaceEntryResult(
            key=entry.entry_key, path=entry.path, status=MarketplaceEntryStatus.OK
        )
    if isinstance(entry, BlockedPlugin):
        return MarketplaceEntryResult(
            key=entry.entry_key,
            path=entry.path,
            status=MarketplaceEntryStatus.BLOCKED,
            reason=entry.reason,
        )
    return MarketplaceEntryResult(
        key=entry.entry_key,
        path=None,
        status=MarketplaceEntryStatus.NOT_SUPPORTED,
        reason=entry.reason,
    )


def plan_marketplace_sync(
    entries: Sequence[ReadyPlugin | BlockedPlugin | UnsupportedPlugin],
    current: Sequence[CurrentSyncedPlugin],
) -> SyncPlan:
    """A blocked or not supported entry keeps its plugin; only an entry that left
    the repository deletes one."""
    by_name = {plugin.name: plugin for plugin in current}
    present = {entry.entry_key for entry in entries}
    create: list[str] = []
    add_version: dict[str, UUID] = {}
    for entry in entries:
        if not isinstance(entry, ReadyPlugin):
            continue
        plugin = by_name.get(entry.entry_key)
        if plugin is None:
            create.append(entry.entry_key)
        elif plugin.file_manifest != entry.file_manifest:
            add_version[entry.entry_key] = plugin.plugin_id
    return SyncPlan(
        create=create,
        add_version=add_version,
        delete_plugin_ids=sorted(
            plugin.plugin_id for plugin in current if plugin.name not in present
        ),
        results=[entry_result(entry) for entry in entries],
    )
