from uuid import UUID, uuid4

from onyx.skills.marketplace.compare import plan_marketplace_sync
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CurrentSyncedPlugin,
    MarketplaceEntryStatus,
    ReadyPlugin,
    UnsupportedPlugin,
)
from onyx.skills.models import PluginBundle, PluginFileEntry, PluginManifest


def _manifest(content: str) -> list[PluginFileEntry]:
    return [PluginFileEntry(path="skills/a/SKILL.md", size=1, sha256=content)]


def _ready(
    key: str,
    content: str = "v1",
    *,
    name: str | None = None,
    path: str | None = None,
) -> ReadyPlugin:
    return ReadyPlugin(
        entry_key=key,
        path=path or key,
        bundle=PluginBundle(
            content=b"",
            manifest=PluginManifest(name=name or key),
            skills=[],
            needs=[],
            warnings=[],
        ),
        file_manifest=_manifest(content),
    )


def _current(name: str, content: str = "v1") -> CurrentSyncedPlugin:
    return CurrentSyncedPlugin(
        plugin_id=uuid4(), name=name, file_manifest=_manifest(content)
    )


def test_new_changed_unchanged_and_moved() -> None:
    same = _current("same")
    changed = _current("changed")
    moved = _current("moved")
    plan = plan_marketplace_sync(
        [
            _ready("same"),
            _ready("changed", "v2"),
            _ready("moved", path="elsewhere/moved"),
            _ready("new"),
        ],
        [same, changed, moved],
    )
    assert plan.create == ["new"]
    assert plan.add_version == {"changed": changed.plugin_id}
    assert plan.delete_plugin_ids == []
    moved_result = next(result for result in plan.results if result.key == "moved")
    assert moved_result.path == "elsewhere/moved"


def test_rename_deletes_the_old_plugin_and_adds_a_new_one() -> None:
    old = _current("old-name")
    plan = plan_marketplace_sync([_ready("new-name", name="old-name")], [old])
    assert plan.delete_plugin_ids == [old.plugin_id]
    assert plan.create == ["new-name"]


def test_entry_comes_back_as_a_new_plugin() -> None:
    plan = plan_marketplace_sync([_ready("back")], [])
    assert plan.create == ["back"]


def test_blocked_and_unsupported_keep_their_plugins() -> None:
    blocked = _current("blocked")
    unsupported = _current("unsupported")
    plan = plan_marketplace_sync(
        [
            BlockedPlugin(entry_key="blocked", path="blocked", reason="bad"),
            UnsupportedPlugin(entry_key="unsupported", reason="no"),
            BlockedPlugin(entry_key="new-blocked", path=None, reason="bad"),
        ],
        [blocked, unsupported],
    )
    assert plan.create == []
    assert plan.add_version == {}
    assert plan.delete_plugin_ids == []
    assert [result.status for result in plan.results] == [
        MarketplaceEntryStatus.BLOCKED,
        MarketplaceEntryStatus.NOT_SUPPORTED,
        MarketplaceEntryStatus.BLOCKED,
    ]


def test_the_manifest_name_does_not_name_the_plugin() -> None:
    kept = _current("kept")
    plan = plan_marketplace_sync(
        [_ready("kept", name="tools"), _ready("other", name="tools")], [kept]
    )
    assert plan.create == ["other"]
    assert plan.add_version == {}


def test_every_removed_entry_deletes_its_plugin() -> None:
    current = [_current(f"plugin-{index}") for index in range(10)]
    plan = plan_marketplace_sync([_ready("plugin-0")], current)
    assert plan.delete_plugin_ids == sorted(plugin.plugin_id for plugin in current[1:])


def test_a_version_with_no_file_list_gets_a_new_version() -> None:
    plugin_id = UUID(int=1)
    current = CurrentSyncedPlugin(plugin_id=plugin_id, name="tool", file_manifest=None)
    assert plan_marketplace_sync([_ready("tool")], [current]).add_version == {
        "tool": plugin_id
    }
