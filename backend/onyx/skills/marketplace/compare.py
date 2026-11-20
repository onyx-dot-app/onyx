from collections.abc import Sequence
from typing import Final
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

DELETE_GUARD_MIN: Final = 5


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
    by_key = {plugin.entry_key: plugin for plugin in current}
    present = {entry.entry_key for entry in entries}
    deleted = [plugin for plugin in current if plugin.entry_key not in present]
    taken_names = {plugin.name for plugin in current if plugin.entry_key in present}
    create: list[str] = []
    add_version: dict[str, UUID] = {}
    results: list[MarketplaceEntryResult] = []
    for entry in entries:
        result = entry_result(entry)
        if isinstance(entry, ReadyPlugin):
            plugin = by_key.get(entry.entry_key)
            if plugin is not None:
                if plugin.file_manifest != entry.file_manifest:
                    add_version[entry.entry_key] = plugin.plugin_id
            elif entry.bundle.manifest.name in taken_names:
                result = MarketplaceEntryResult(
                    key=entry.entry_key,
                    path=entry.path,
                    status=MarketplaceEntryStatus.BLOCKED,
                    reason="Another plugin in this marketplace is named "
                    f"'{entry.bundle.manifest.name}'.",
                )
            else:
                create.append(entry.entry_key)
                taken_names.add(entry.bundle.manifest.name)
        results.append(result)
    return SyncPlan(
        create=create,
        add_version=add_version,
        delete_plugin_ids=sorted(plugin.plugin_id for plugin in deleted),
        results=results,
        needs_confirmation=len(deleted) > DELETE_GUARD_MIN
        and len(deleted) * 2 > len(current),
    )
