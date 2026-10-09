from collections.abc import Callable
from typing import cast

from box_sdk_gen import BoxClient
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.web_link import WebLink

from onyx.access.models import ExternalAccess
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
    noop_fallback,
)


def resolve_box_ancestor_access(
    client: BoxClient,
    path_entries: list[FolderMini] | None,
    enterprise_id: str,
) -> ExternalAccess | None:
    resolve_access = cast(
        Callable[[BoxClient, list[FolderMini] | None, str], ExternalAccess | None],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.box.access",
            "resolve_box_ancestor_access",
            fallback=noop_fallback,
        ),
    )
    return resolve_access(client, path_entries, enterprise_id)


def resolve_box_folder_access(
    client: BoxClient,
    folder_id: str,
    inherited_access: ExternalAccess | None,
    enterprise_id: str,
) -> ExternalAccess | None:
    resolve_access = cast(
        Callable[[BoxClient, str, ExternalAccess | None, str], ExternalAccess | None],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.box.access",
            "resolve_box_folder_access",
            fallback=noop_fallback,
        ),
    )
    return resolve_access(client, folder_id, inherited_access, enterprise_id)


def resolve_box_file_access(
    client: BoxClient,
    file: FileFull,
    folder_access: ExternalAccess,
    enterprise_id: str,
) -> ExternalAccess | None:
    resolve_access = cast(
        Callable[[BoxClient, FileFull, ExternalAccess, str], ExternalAccess | None],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.box.access",
            "resolve_box_file_access",
            fallback=noop_fallback,
        ),
    )
    return resolve_access(client, file, folder_access, enterprise_id)


def resolve_box_web_link_access(
    web_link: WebLink,
    folder_access: ExternalAccess,
    enterprise_id: str,
) -> ExternalAccess | None:
    resolve_access = cast(
        Callable[[WebLink, ExternalAccess, str], ExternalAccess | None],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.box.access",
            "resolve_box_web_link_access",
            fallback=noop_fallback,
        ),
    )
    return resolve_access(web_link, folder_access, enterprise_id)
