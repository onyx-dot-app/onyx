from box_sdk_gen import BoxClient
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.schemas.collaboration import Collaboration, CollaborationStatusField
from box_sdk_gen.schemas.file import FileSharedLinkField
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder import FolderSharedLinkField
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.group_mini import GroupMini
from box_sdk_gen.schemas.user_collaborations import UserCollaborations
from box_sdk_gen.schemas.user_mini import UserMini
from box_sdk_gen.schemas.web_link import WebLink, WebLinkSharedLinkField
from pydantic import BaseModel, Field

from onyx.access.models import ExternalAccess
from onyx.connectors.box.connector import (
    BOX_ROOT_FOLDER_ID,
    box_all_enterprise_users_group_id,
    box_api_status_code,
    box_group_id,
    normalize_box_login,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_COLLABORATIONS_PAGE_SIZE = 1000
_MAX_PAGINATION_ITERATIONS = 10_000

# Every accepted Box collaboration role except `uploader` can read or preview.
# Keeping an allowlist ensures new SDK roles fail closed until reviewed.
_READ_ACCESS_COLLABORATION_ROLES = {
    "editor",
    "viewer",
    "previewer",
    "previewer uploader",
    "viewer uploader",
    "co-owner",
    "owner",
}


class BoxAccessContext(BaseModel):
    user_emails: set[str] = Field(default_factory=set)
    group_ids: set[str] = Field(default_factory=set)
    is_public: bool = False

    @classmethod
    def from_external_access(
        cls, external_access: ExternalAccess | None
    ) -> "BoxAccessContext":
        if external_access is None:
            return cls()
        return cls(
            user_emails=external_access.external_user_emails,
            group_ids=external_access.external_user_group_ids,
            is_public=external_access.is_public,
        )

    def merged_with(self, other: "BoxAccessContext") -> "BoxAccessContext":
        return BoxAccessContext(
            user_emails=self.user_emails | other.user_emails,
            group_ids=self.group_ids | other.group_ids,
            is_public=self.is_public or other.is_public,
        )

    def to_external_access(self) -> ExternalAccess:
        return ExternalAccess(
            external_user_emails=self.user_emails,
            external_user_group_ids=self.group_ids,
            is_public=self.is_public,
        )


def apply_collaborations_to_access(
    access: BoxAccessContext,
    collaborations: list[Collaboration],
) -> BoxAccessContext:
    """Add users and groups from accepted, read-capable Box collaborations."""
    user_emails = set(access.user_emails)
    group_ids = set(access.group_ids)
    for collaboration in collaborations:
        if (
            collaboration.status != CollaborationStatusField.ACCEPTED
            or collaboration.role is None
        ):
            continue
        role_value = str(collaboration.role.value)
        if role_value not in _READ_ACCESS_COLLABORATION_ROLES:
            if role_value != "uploader":
                logger.warning("Unrecognized Box collaboration role: %s", role_value)
            continue
        accessible_by = collaboration.accessible_by
        if isinstance(accessible_by, UserCollaborations) and accessible_by.login:
            user_emails.add(normalize_box_login(accessible_by.login))
        elif isinstance(accessible_by, GroupMini):
            group_ids.add(box_group_id(accessible_by.id))
    return BoxAccessContext(
        user_emails=user_emails,
        group_ids=group_ids,
        is_public=access.is_public,
    )


def apply_shared_link_to_access(
    access: BoxAccessContext,
    shared_link: FileSharedLinkField
    | FolderSharedLinkField
    | WebLinkSharedLinkField
    | None,
    enterprise_id: str,
) -> BoxAccessContext:
    if shared_link is None:
        return access
    shared_link_access = (
        shared_link.effective_access.value
        if shared_link.effective_access is not None
        else shared_link.access.value
        if shared_link.access is not None
        else None
    )
    if shared_link_access == "open" and not shared_link.is_password_enabled:
        return access.merged_with(BoxAccessContext(is_public=True))
    if shared_link_access == "company":
        return access.merged_with(
            BoxAccessContext(
                group_ids={box_all_enterprise_users_group_id(enterprise_id)}
            )
        )
    return access


def _apply_owner(
    access: BoxAccessContext, owned_by: UserMini | None
) -> BoxAccessContext:
    if owned_by is None or not owned_by.login:
        return access
    return access.merged_with(
        BoxAccessContext(user_emails={normalize_box_login(owned_by.login)})
    )


def _fetch_collaborations_access(
    client: BoxClient,
    base_access: BoxAccessContext,
    item_id: str,
    is_folder: bool,
) -> BoxAccessContext:
    manager = client.list_collaborations
    fetch = (
        manager.get_folder_collaborations
        if is_folder
        else manager.get_file_collaborations
    )
    access = base_access
    marker: str | None = None
    for _ in range(_MAX_PAGINATION_ITERATIONS):
        collaborations = fetch(item_id, limit=_COLLABORATIONS_PAGE_SIZE, marker=marker)
        access = apply_collaborations_to_access(access, collaborations.entries or [])
        marker = collaborations.next_marker
        if not marker:
            return access
    raise RuntimeError(f"Box collaboration pagination did not terminate for {item_id}")


def resolve_box_folder_access(
    client: BoxClient,
    folder_id: str,
    inherited_access: ExternalAccess | None,
    enterprise_id: str,
) -> ExternalAccess:
    access = BoxAccessContext.from_external_access(inherited_access)
    # Box's root folder cannot be collaborated; the endpoint returns HTTP 400.
    if folder_id != BOX_ROOT_FOLDER_ID:
        access = _fetch_collaborations_access(client, access, folder_id, is_folder=True)
    folder = client.folders.get_folder_by_id(
        folder_id, fields=["shared_link", "owned_by"]
    )
    access = _apply_owner(access, folder.owned_by)
    return apply_shared_link_to_access(
        access, folder.shared_link, enterprise_id
    ).to_external_access()


def resolve_box_ancestor_access(
    client: BoxClient,
    path_entries: list[FolderMini] | None,
    enterprise_id: str,
) -> ExternalAccess:
    access = ExternalAccess.empty()
    for ancestor in path_entries or []:
        if ancestor.id == BOX_ROOT_FOLDER_ID:
            continue
        try:
            access = resolve_box_folder_access(
                client, ancestor.id, access, enterprise_id
            )
        except BoxAPIError as error:
            status = box_api_status_code(error)
            if status not in (403, 404):
                raise
            logger.warning(
                "Cannot read ancestor folder %s while resolving inherited "
                "access (status=%s); skipping it.",
                ancestor.id,
                status,
            )
    return access


def resolve_box_file_access(
    client: BoxClient,
    file: FileFull,
    folder_access: ExternalAccess,
    enterprise_id: str,
) -> ExternalAccess:
    access = _apply_owner(
        BoxAccessContext.from_external_access(folder_access), file.owned_by
    )
    if file.has_collaborations:
        access = _fetch_collaborations_access(client, access, file.id, is_folder=False)
    return apply_shared_link_to_access(
        access, file.shared_link, enterprise_id
    ).to_external_access()


def resolve_box_web_link_access(
    web_link: WebLink,
    folder_access: ExternalAccess,
    enterprise_id: str,
) -> ExternalAccess:
    access = BoxAccessContext.from_external_access(folder_access)
    return apply_shared_link_to_access(
        access, web_link.shared_link, enterprise_id
    ).to_external_access()
