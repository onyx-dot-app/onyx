from onyx.connectors.interfaces import RunScopedCache
from onyx.connectors.microsoft_utils.models import (
    SharepointLibraryInheritance,
    SharepointListItemInheritance,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_access import (
    INHERITANCE_OFF_TTL_SECONDS,
    SharedSharepointPermissionCache,
)
from onyx.connectors.sharepoint.permission_inheritance import inherited_access_sources

_ROOT = "/sites/eng/Shared Documents"
_LIST_ID = "list-1"


def _item(
    item_id: int, path: str, *, folder: bool = False, unique: bool = False
) -> SharepointListItemInheritance:
    file_ref = f"{_ROOT}/{path}"
    return SharepointListItemInheritance(
        item_id=item_id,
        is_folder=folder,
        file_ref=file_ref,
        file_dir_ref=file_ref.rpartition("/")[0],
        has_unique_role_assignments=unique,
    )


def _library(
    items: list[SharepointListItemInheritance], unique: bool = False
) -> SharepointLibraryInheritance:
    return SharepointLibraryInheritance(
        root_folder_server_relative_url=_ROOT,
        has_unique_role_assignments=unique,
        items=items,
    )


def _folder(item_id: int) -> SharepointSecurable:
    return SharepointSecurable(
        kind=SharepointSecurableKind.LIST_ITEM, list_id=_LIST_ID, item_id=item_id
    )


def test_each_file_takes_its_nearest_unique_ancestor() -> None:
    library = _library(
        [
            _item(1, "A", folder=True, unique=True),
            _item(2, "A/B", folder=True),
            _item(3, "A/B/deep.txt"),
            _item(4, "A/top.txt"),
            _item(5, "C", folder=True),
            _item(6, "C/in-c.txt"),
            _item(7, "root.txt"),
            _item(8, "A/B/own.txt", unique=True),
        ]
    )

    sources = inherited_access_sources(library, _LIST_ID)

    site = SharepointSecurable(kind=SharepointSecurableKind.SITE)
    assert sources == {3: _folder(1), 4: _folder(1), 6: site, 7: site}


def test_a_unique_library_is_the_source_at_the_root() -> None:
    library = _library([_item(1, "root.txt"), _item(2, "D", folder=True)], unique=True)

    assert inherited_access_sources(library, _LIST_ID) == {
        1: SharepointSecurable(kind=SharepointSecurableKind.LIBRARY, list_id=_LIST_ID)
    }


def test_a_file_under_a_folder_missing_from_the_read_has_no_source() -> None:
    """Fail closed: the read does not show if the missing folder breaks
    inheritance."""
    library = _library(
        [
            _item(1, "A", folder=True),
            _item(2, "A/B/lost.txt"),
            _item(3, "A/found.txt"),
            _item(4, "A/B/also-lost.txt"),
        ]
    )

    assert inherited_access_sources(library, _LIST_ID) == {
        3: SharepointSecurable(kind=SharepointSecurableKind.SITE)
    }


def test_paths_match_without_case() -> None:
    library = _library(
        [
            _item(1, "Folder", folder=True, unique=True),
            SharepointListItemInheritance(
                item_id=2,
                is_folder=False,
                file_ref=f"{_ROOT.upper()}/FOLDER/x.txt",
                file_dir_ref=f"{_ROOT.upper()}/FOLDER",
                has_unique_role_assignments=False,
            ),
        ]
    )

    assert inherited_access_sources(library, _LIST_ID) == {2: _folder(1)}


def test_a_file_outside_the_library_root_has_no_source() -> None:
    library = _library(
        [
            SharepointListItemInheritance(
                item_id=1,
                is_folder=False,
                file_ref="/sites/other/Docs/x.txt",
                file_dir_ref="/sites/other/Docs",
                has_unique_role_assignments=False,
            )
        ]
    )

    assert inherited_access_sources(library, _LIST_ID) == {}


class _RunCache(RunScopedCache):
    """The cache of one listing run. ``values`` keeps each value with its
    time to live."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, int]] = {}

    def get(self, key: str) -> str | None:
        entry = self.values.get(key)
        return entry[0] if entry else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = (value, ttl_seconds)


def test_inheritance_stays_off_for_the_rest_of_the_run() -> None:
    """The marker outlives any listing run, and a worker that saw it keeps
    it when the run cache later loses it."""
    run_cache = _RunCache()
    first = SharedSharepointPermissionCache(shared=run_cache)
    second = SharedSharepointPermissionCache(shared=run_cache)
    assert not second.is_inheritance_off()

    first.turn_inheritance_off()

    assert [ttl for _value, ttl in run_cache.values.values()] == [
        INHERITANCE_OFF_TTL_SECONDS
    ]
    assert second.is_inheritance_off()
    run_cache.values.clear()
    assert second.is_inheritance_off()
    assert not SharedSharepointPermissionCache(shared=_RunCache()).is_inheritance_off()
