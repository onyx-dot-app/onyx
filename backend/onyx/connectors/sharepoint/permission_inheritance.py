"""Which files of a library have no role assignments of their own, and the
securable they take them from.

SharePoint sets ``HasUniqueRoleAssignments`` on each item where inheritance is
broken, also when a sharing link breaks it. An item without it has the role
assignments of its nearest folder that has them, else of the library, else of
the site. The stub listing reads the flags of a library in one read for each
5,000 items, so that conversion reads permissions only for the files that have
their own, and one time for each folder, library or site that others inherit
from.
"""

from onyx.connectors.microsoft_utils.models import (
    SharepointLibraryInheritance,
    SharepointSecurable,
    SharepointSecurableKind,
)


def _path_key(server_relative_path: str) -> str:
    """SharePoint paths do not depend on case."""
    return server_relative_path.rstrip("/").casefold()


def _parent_key(path_key: str) -> str:
    return path_key.rpartition("/")[0]


def inherited_access_sources(
    library: SharepointLibraryInheritance, list_id: str
) -> dict[int, SharepointSecurable]:
    """The securable whose role assignments each inheriting file of the
    library has, by the file's list item id.

    A file is left out, so that it gets a permission read of its own, when it
    has role assignments of its own, and when a folder between it and the
    library root is not in the read (the read is then not complete for it).
    """
    root = _path_key(library.root_folder_server_relative_url)
    library_source = (
        SharepointSecurable(kind=SharepointSecurableKind.LIBRARY, list_id=list_id)
        if library.has_unique_role_assignments
        else SharepointSecurable(kind=SharepointSecurableKind.SITE)
    )
    folders = {
        _path_key(item.file_ref): item for item in library.items if item.is_folder
    }
    # The source of each folder path, None when it cannot be known.
    resolved: dict[str, SharepointSecurable | None] = {root: library_source}

    def source_of(folder_key: str) -> SharepointSecurable | None:
        walked: list[str] = []
        key = folder_key
        while key not in resolved:
            folder = folders.get(key)
            if folder is None or not key.startswith(root + "/"):
                source = None
                break
            if folder.has_unique_role_assignments:
                source = SharepointSecurable(
                    kind=SharepointSecurableKind.LIST_ITEM,
                    list_id=list_id,
                    item_id=folder.item_id,
                )
                break
            walked.append(key)
            key = _parent_key(key)
        else:
            source = resolved[key]
        for walked_key in (*walked, key):
            resolved.setdefault(walked_key, source)
        return source

    sources: dict[int, SharepointSecurable] = {}
    for item in library.items:
        if item.is_folder or item.has_unique_role_assignments:
            continue
        source = source_of(_path_key(item.file_dir_ref))
        if source is not None:
            sources[item.item_id] = source
    return sources
