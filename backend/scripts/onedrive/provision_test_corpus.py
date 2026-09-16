"""Provision the fixed OneDrive connector corpus in a dedicated test subtree."""

from __future__ import annotations

import argparse
import io
import logging
import os
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit

import requests
from docx import Document as DocxDocument
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.listitems.listitem import ListItem
from pydantic import AliasChoices, BaseModel, Field

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    MicrosoftAuthMethod,
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GRAPH_API_MAX_RETRIES,
    GRAPH_API_RETRYABLE_STATUSES,
    GraphApiClient,
    backoff_seconds,
    graph_error_code,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
)
from onyx.connectors.sharepoint.connector import acquire_token_for_rest
from tests.utils.aws_secrets import get_secrets
from tests.utils.secret_names import TestSecret

logger = logging.getLogger(__name__)

FIXTURE_ROOT_NAME = "Onyx OneDrive Connector Tests"
VISIBLE_GROUP_NAME = "Onyx OneDrive Visible Test Group"
VISIBLE_GROUP_ALIAS = "onyx-onedrive-visible-test"
HIDDEN_GROUP_NAME = "Onyx OneDrive Hidden Test Group"
HIDDEN_GROUP_ALIAS = "onyx-onedrive-hidden-test"
DEFAULT_OWNER_UPN = "test@danswerai.onmicrosoft.com"
DEFAULT_PRIMARY_UPN = "subash@onyx.app"
DEFAULT_SECOND_OWNER_UPN = DEFAULT_PRIMARY_UPN
DEFAULT_ALTERNATE_UPN = "raunak@onyx.app"
IDENTITY_FOLDER_NAME = "90-identity"
IDENTITY_FILE_NAME = "cross-drive-duplicate.docx"
READ_ROLE_NAME = "Read"
SHARING_ROLE_READ = "read"
GRAPH_API_VERSION = "v1.0"
TEST_FILE_SIZE_BYTES = 1024
DELETE_POLL_ATTEMPTS = 10
DELETE_POLL_SECONDS = 1
GROUP_PROVISION_ATTEMPTS = 10
GROUP_PROVISION_POLL_SECONDS = 2
OPTIONAL_LINK_REJECTION_STATUSES = frozenset({400, 403})
GRAPH_RESOURCE_SEGMENTS = frozenset(
    {"directoryObjects", "drives", "groups", "items", "sites", "users"}
)

OWNER_UPN_ENV = "ONEDRIVE_TEST_OWNER_UPN"
SECOND_OWNER_UPN_ENV = "ONEDRIVE_TEST_SECOND_OWNER_UPN"
PRIMARY_UPN_ENV = "ONEDRIVE_TEST_PRIMARY_UPN"
ALTERNATE_UPN_ENV = "ONEDRIVE_TEST_ALTERNATE_UPN"


class FolderPath(str, Enum):
    PRIVATE = "00-private"
    DIRECT = "10-direct"
    INHERITED = "20-inherited-subash"
    INHERITED_NESTED = "20-inherited-subash/nested"
    RESTRICTED = "20-inherited-subash/restricted-raunak"
    GROUPS = "30-groups"
    LINKS = "40-links"
    MOVE = "50-move"
    MOVE_SOURCE = "50-move/source-subash"
    MOVE_DESTINATION = "50-move/destination-raunak"
    MUTATIONS = "60-permission-mutations"
    REMOVE_SHARE = "60-permission-mutations/remove-share"
    RESTORE_PARENT = "60-permission-mutations/restore-parent-subash"
    CONTENT_MUTATIONS = "70-content-mutations"
    FILTERING = "80-filtering"
    IDENTITY = IDENTITY_FOLDER_NAME


class FilePath(str, Enum):
    PRIVATE = "00-private/private-owner-only.docx"
    DIRECT = "10-direct/direct-subash.docx"
    INHERITED = "20-inherited-subash/inherited-child.docx"
    INHERITED_NESTED = "20-inherited-subash/nested/inherited-grandchild.docx"
    RESTRICTED = "20-inherited-subash/restricted-raunak/restricted-child.docx"
    VISIBLE_GROUP = "30-groups/visible-group.docx"
    HIDDEN_GROUP = "30-groups/hidden-group.docx"
    ANONYMOUS_LINK = "40-links/anonymous-link.docx"
    ORGANIZATION_LINK = "40-links/organization-link.docx"
    MOVE = "50-move/source-subash/move-between-roots.docx"
    MOVE_DESTINATION = "50-move/destination-raunak/move-between-roots.docx"
    REMOVE_SHARE = "60-permission-mutations/remove-share/remove-direct-share.docx"
    RESTORE_INHERITANCE = (
        "60-permission-mutations/restore-parent-subash/restore-inheritance.docx"
    )
    UPDATE = "70-content-mutations/update-during-delta.docx"
    DELETE = "70-content-mutations/delete-during-delta.docx"
    EXCLUDED = "80-filtering/excluded.tmp"
    OVER_SIZE = "80-filtering/over-test-size-limit.txt"
    UNSUPPORTED = "80-filtering/unsupported.test-extension"
    IDENTITY = f"{IDENTITY_FOLDER_NAME}/{IDENTITY_FILE_NAME}"


class FixturePhase(str, Enum):
    DESCRIBE = "describe"
    SETUP = "setup"
    MUTATE = "mutate"


class GroupVisibility(str, Enum):
    PRIVATE = "Private"
    HIDDEN_MEMBERSHIP = "HiddenMembership"


class LinkScope(str, Enum):
    ANONYMOUS = "anonymous"
    ORGANIZATION = "organization"


class GraphFixtureError(RuntimeError):
    def __init__(self, method: str, path: str, status_code: int, code: str) -> None:
        super().__init__(
            f"Graph fixture operation failed: {method} {_redact_graph_path(path)} "
            f"returned {status_code} ({code}). "
            "Check the existing certificate app's fixture-writer permissions."
        )
        self.status_code = status_code


def _redact_graph_path(path: str) -> str:
    parts = urlsplit(path)
    segments = parts.path.split("/")
    for index, segment in enumerate(segments[:-1]):
        if segment in GRAPH_RESOURCE_SEGMENTS:
            segments[index + 1] = "<id>"
    return "/".join(segments)


class GraphIdentity(BaseModel):
    id: str


class GraphUser(GraphIdentity):
    user_principal_name: str = Field(
        validation_alias=AliasChoices("userPrincipalName", "user_principal_name")
    )


class SharePointIds(BaseModel):
    site_id: str | None = Field(default=None, alias="siteId")
    list_id: str | None = Field(default=None, alias="listId")
    list_item_id: str | None = Field(default=None, alias="listItemId")


class GraphDrive(GraphIdentity):
    name: str
    web_url: str = Field(alias="webUrl")
    drive_type: str = Field(alias="driveType")
    sharepoint_ids: SharePointIds | None = Field(default=None, alias="sharepointIds")


class GraphItem(GraphIdentity):
    name: str
    web_url: str = Field(alias="webUrl")
    sharepoint_ids: SharePointIds | None = Field(default=None, alias="sharepointIds")


class GraphSite(GraphIdentity):
    web_url: str = Field(alias="webUrl")


class GraphGroup(GraphIdentity):
    display_name: str = Field(alias="displayName")
    mail_nickname: str = Field(alias="mailNickname")
    visibility: str | None = None


class GraphIdentitySet(BaseModel):
    user: GraphIdentity | None = None
    group: GraphIdentity | None = None


class GraphPermission(BaseModel):
    id: str
    granted_to_v2: GraphIdentitySet | None = Field(default=None, alias="grantedToV2")
    granted_to_identities_v2: list[GraphIdentitySet] = Field(
        default_factory=list, alias="grantedToIdentitiesV2"
    )

    def grants_principal(self, principal_id: str) -> bool:
        identities = [self.granted_to_v2, *self.granted_to_identities_v2]
        return any(
            identity is not None
            and (
                (identity.user is not None and identity.user.id == principal_id)
                or (identity.group is not None and identity.group.id == principal_id)
            )
            for identity in identities
        )


class GraphCollection(BaseModel):
    value: list[dict[str, Any]]
    next_link: str | None = Field(default=None, alias="@odata.nextLink")


class FixtureConfig(BaseModel):
    owner_upn: str = DEFAULT_OWNER_UPN
    second_owner_upn: str = DEFAULT_SECOND_OWNER_UPN
    primary_upn: str = DEFAULT_PRIMARY_UPN
    alternate_upn: str = DEFAULT_ALTERNATE_UPN
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
    authority_host: str = DEFAULT_AUTHORITY_HOST


class CertificateAppCredentials(BaseModel):
    client_id: str
    private_key: str
    certificate_password: str
    directory_id: str


class CliArgs(BaseModel):
    phase: FixturePhase
    apply: bool


class FixtureState(BaseModel):
    owner: GraphUser
    second_owner: GraphUser
    primary_user: GraphUser
    alternate_user: GraphUser
    drive: GraphDrive
    second_drive: GraphDrive
    site: GraphSite
    root_item: GraphItem
    folders: dict[FolderPath, GraphItem]
    files: dict[FilePath, GraphItem]
    visible_group: GraphGroup
    hidden_group: GraphGroup
    second_drive_duplicate: GraphItem


def relative_to_fixture_root(path: FolderPath | FilePath) -> str:
    return f"{FIXTURE_ROOT_NAME}/{path.value}"


def validate_fixture_paths() -> None:
    for path in (*FolderPath, *FilePath):
        relative = relative_to_fixture_root(path)
        if not relative.startswith(f"{FIXTURE_ROOT_NAME}/"):
            raise RuntimeError(f"Unsafe fixture path: {relative}")


def exact_membership_changes(
    current_member_ids: set[str], expected_member_ids: set[str]
) -> tuple[set[str], set[str]]:
    return (
        expected_member_ids - current_member_ids,
        current_member_ids - expected_member_ids,
    )


def _docx_bytes(text: str) -> bytes:
    document = DocxDocument()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def fixture_file_bytes(path: FilePath, mutated: bool = False) -> bytes:
    marker = "mutated" if mutated else "baseline"
    content = f"Onyx OneDrive fixture: {path.value} ({marker})"
    if path is FilePath.OVER_SIZE:
        return content.encode().ljust(TEST_FILE_SIZE_BYTES, b"x")
    if path.value.endswith(".docx"):
        return _docx_bytes(content)
    return content.encode()


GraphModel = TypeVar("GraphModel", bound=BaseModel)


class FixtureGraphClient(GraphApiClient):
    def __init__(
        self, get_access_token: Callable[[], str], graph_api_host: str
    ) -> None:
        base_url = f"{graph_api_host.rstrip('/')}/{GRAPH_API_VERSION}"
        super().__init__(get_access_token, base_url)
        self._get_access_token = get_access_token
        self.base_url = base_url

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", url, params=params, headers=headers).json()

    def get_model(
        self,
        path: str,
        model: type[GraphModel],
        params: dict[str, str] | None = None,
    ) -> GraphModel:
        return model.model_validate(self.get_json(self._url(path), params))

    def get_optional_item(self, path: str) -> GraphItem | None:
        try:
            return GraphItem.model_validate(self.get_json(self._url(path)))
        except GraphFixtureError as error:
            if error.status_code == 404:
                return None
            raise

    def get_collection(
        self, path: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        page_url: str | None = self._url(path)
        while page_url:
            page = GraphCollection.model_validate(self.get_json(page_url, params))
            values.extend(page.value)
            page_url = page.next_link
            params = None
        return values

    def post_model(
        self,
        path: str,
        body: dict[str, Any],
        model: type[GraphModel],
    ) -> GraphModel:
        response = self._request("POST", path, json=body)
        return model.model_validate(response.json())

    def put_item(self, path: str, content: bytes) -> GraphItem:
        response = self._request(
            "PUT",
            path,
            data=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return GraphItem.model_validate(response.json())

    def patch_item(self, path: str, body: dict[str, Any]) -> GraphItem:
        response = self._request("PATCH", path, json=body)
        return GraphItem.model_validate(response.json())

    def post(self, path: str, body: dict[str, Any]) -> None:
        self._request("POST", path, json=body)

    def patch(self, path: str, body: dict[str, Any]) -> None:
        self._request("PATCH", path, json=body)

    def delete(self, path: str, allow_missing: bool = False) -> None:
        self._request("DELETE", path, allow_missing=allow_missing)

    def _url(self, path: str) -> str:
        return (
            path
            if path.startswith("https://")
            else f"{self.base_url}/{path.lstrip('/')}"
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        allow_missing: bool = False,
    ) -> requests.Response:
        url = self._url(path)
        for attempt in range(GRAPH_API_MAX_RETRIES + 1):
            request_headers = {
                "Authorization": f"Bearer {self._get_access_token()}",
                **(headers or {}),
            }
            response = requests.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if allow_missing and response.status_code == 404:
                return response
            if (
                response.status_code in GRAPH_API_RETRYABLE_STATUSES
                and attempt < GRAPH_API_MAX_RETRIES
            ):
                time.sleep(
                    backoff_seconds(attempt, response.headers.get("Retry-After"))
                )
                continue
            if response.ok:
                return response
            code = graph_error_code(response)
            raise GraphFixtureError(method, path, response.status_code, code)
        raise RuntimeError(
            f"Graph fixture operation exhausted retries: {method} {path}"
        )


class OneDriveFixtureProvisioner:
    def __init__(
        self,
        config: FixtureConfig,
        graph: FixtureGraphClient,
        build_rest_context: Callable[[str], ClientContext],
    ) -> None:
        self.config = config
        self.graph = graph
        self._build_rest_context = build_rest_context

    def setup(self) -> FixtureState:
        validate_fixture_paths()
        owner = self._get_user(self.config.owner_upn)
        second_owner = self._get_user(self.config.second_owner_upn)
        if owner.id == second_owner.id:
            raise RuntimeError("The fixture requires two distinct drive owners")
        primary_user = self._get_user(self.config.primary_upn)
        alternate_user = self._get_user(self.config.alternate_upn)
        drive = self._get_drive(owner.id)
        site = self._get_drive_site(drive)

        self._delete_existing_root(drive.id)
        drive_root = self._get_drive_root(drive.id)
        root_item = self._create_folder(drive.id, drive_root.id, FIXTURE_ROOT_NAME)
        folders = self._create_folders(drive.id, root_item)
        files = self._create_files(drive.id, folders)
        second_drive = self._get_drive(second_owner.id)
        second_drive_duplicate = self._create_second_drive_duplicate(second_drive)

        visible_group = self._ensure_group(
            VISIBLE_GROUP_NAME,
            VISIBLE_GROUP_ALIAS,
            GroupVisibility.PRIVATE,
            {primary_user.id},
        )
        hidden_group = self._ensure_group(
            HIDDEN_GROUP_NAME,
            HIDDEN_GROUP_ALIAS,
            GroupVisibility.HIDDEN_MEMBERSHIP,
            {alternate_user.id},
        )

        state = FixtureState(
            owner=owner,
            second_owner=second_owner,
            primary_user=primary_user,
            alternate_user=alternate_user,
            drive=drive,
            second_drive=second_drive,
            site=site,
            root_item=root_item,
            folders=folders,
            files=files,
            visible_group=visible_group,
            hidden_group=hidden_group,
            second_drive_duplicate=second_drive_duplicate,
        )
        self._apply_baseline_permissions(state)
        return state

    def mutate(self) -> None:
        owner = self._get_user(self.config.owner_upn)
        primary_user = self._get_user(self.config.primary_upn)
        drive = self._get_drive(owner.id)
        site = self._get_drive_site(drive)

        source = self._get_item_by_path(drive.id, FilePath.MOVE)
        destination = self._get_item_by_path(drive.id, FilePath.MOVE_DESTINATION)
        destination_folder = self._require_item_by_path(
            drive.id, FolderPath.MOVE_DESTINATION
        )
        if source is not None:
            self.graph.patch_item(
                f"drives/{drive.id}/items/{source.id}",
                {"parentReference": {"id": destination_folder.id}},
            )
        elif destination is None:
            raise RuntimeError("Move fixture is missing from source and destination")

        remove_share = self._require_item_by_path(drive.id, FilePath.REMOVE_SHARE)
        self._remove_principal_permissions(drive.id, remove_share.id, primary_user.id)

        restore = self._require_item_by_path(drive.id, FilePath.RESTORE_INHERITANCE)
        self._reset_inheritance(site.web_url, drive.id, restore)

        update = self._require_item_by_path(drive.id, FilePath.UPDATE)
        self.graph.put_item(
            f"drives/{drive.id}/items/{update.id}/content",
            fixture_file_bytes(FilePath.UPDATE, mutated=True),
        )

        delete = self._get_item_by_path(drive.id, FilePath.DELETE)
        if delete is not None:
            self.graph.delete(f"drives/{drive.id}/items/{delete.id}")

    def _get_user(self, upn: str) -> GraphUser:
        encoded = quote(upn, safe="")
        result = self.graph.get_model(
            f"users/{encoded}",
            GraphUser,
            {"$select": "id,userPrincipalName"},
        )
        return GraphUser.model_validate(result)

    def _get_drive(self, user_id: str) -> GraphDrive:
        result = self.graph.get_model(
            f"users/{user_id}/drive",
            GraphDrive,
            {"$select": "id,name,driveType,webUrl,sharepointIds"},
        )
        return GraphDrive.model_validate(result)

    def _get_drive_root(self, drive_id: str) -> GraphItem:
        result = self.graph.get_model(
            f"drives/{drive_id}/root",
            GraphItem,
            {"$select": "id,name,webUrl,sharepointIds"},
        )
        return GraphItem.model_validate(result)

    def _get_drive_site(self, drive: GraphDrive) -> GraphSite:
        site_id = drive.sharepoint_ids.site_id if drive.sharepoint_ids else None
        if site_id is None:
            root_ids = self._get_drive_root(drive.id).sharepoint_ids
            site_id = root_ids.site_id if root_ids else None
        if not site_id:
            raise RuntimeError("The test drive did not return a SharePoint site ID")
        result = self.graph.get_model(
            f"sites/{site_id}", GraphSite, {"$select": "id,webUrl"}
        )
        return GraphSite.model_validate(result)

    def _delete_existing_root(self, drive_id: str) -> None:
        root = self._get_item_by_relative_path(drive_id, FIXTURE_ROOT_NAME)
        if root is None:
            return
        self.graph.delete(f"drives/{drive_id}/items/{root.id}")
        for _ in range(DELETE_POLL_ATTEMPTS):
            if self._get_item_by_relative_path(drive_id, FIXTURE_ROOT_NAME) is None:
                return
            time.sleep(DELETE_POLL_SECONDS)
        raise RuntimeError("Timed out while deleting the existing fixture root")

    def _create_folder(self, drive_id: str, parent_id: str, name: str) -> GraphItem:
        result = self.graph.post_model(
            f"drives/{drive_id}/items/{parent_id}/children",
            {
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "replace",
            },
            GraphItem,
        )
        return GraphItem.model_validate(result)

    def _create_folders(
        self, drive_id: str, root_item: GraphItem
    ) -> dict[FolderPath, GraphItem]:
        folders: dict[FolderPath, GraphItem] = {}
        for path in sorted(FolderPath, key=lambda value: value.value.count("/")):
            parent_path, name = (
                path.value.rsplit("/", 1) if "/" in path.value else ("", path.value)
            )
            parent = root_item if not parent_path else folders[FolderPath(parent_path)]
            folders[path] = self._create_folder(drive_id, parent.id, name)
        return folders

    def _create_files(
        self, drive_id: str, folders: dict[FolderPath, GraphItem]
    ) -> dict[FilePath, GraphItem]:
        files: dict[FilePath, GraphItem] = {}
        for path in FilePath:
            if path is FilePath.MOVE_DESTINATION:
                continue
            parent_path, name = path.value.rsplit("/", 1)
            parent = folders[FolderPath(parent_path)]
            encoded_name = quote(name, safe="")
            files[path] = self.graph.put_item(
                f"drives/{drive_id}/items/{parent.id}:/{encoded_name}:/content",
                fixture_file_bytes(path),
            )
        return files

    def _create_second_drive_duplicate(self, drive: GraphDrive) -> GraphItem:
        self._delete_existing_root(drive.id)
        drive_root = self._get_drive_root(drive.id)
        fixture_root = self._create_folder(drive.id, drive_root.id, FIXTURE_ROOT_NAME)
        identity_folder = self._create_folder(
            drive.id, fixture_root.id, IDENTITY_FOLDER_NAME
        )
        return self.graph.put_item(
            f"drives/{drive.id}/items/{identity_folder.id}:/{IDENTITY_FILE_NAME}:/content",
            fixture_file_bytes(FilePath.IDENTITY),
        )

    def _ensure_group(
        self,
        display_name: str,
        mail_nickname: str,
        visibility: GroupVisibility,
        member_ids: set[str],
    ) -> GraphGroup:
        escaped_alias = mail_nickname.replace("'", "''")
        matches = self.graph.get_collection(
            "groups",
            {
                "$filter": f"mailNickname eq '{escaped_alias}'",
                "$select": "id,displayName,mailNickname,visibility",
            },
        )
        if len(matches) > 1:
            raise RuntimeError(f"Multiple fixture groups use alias {mail_nickname}")

        if matches:
            group = GraphGroup.model_validate(matches[0])
            if group.visibility != visibility.value:
                raise RuntimeError(
                    f"Fixture group {mail_nickname} has visibility "
                    f"{group.visibility!r}; expected {visibility.value!r}"
                )
            self.graph.patch(
                f"groups/{group.id}",
                {"displayName": display_name},
            )
            group.display_name = display_name
        else:
            result = self.graph.post_model(
                "groups",
                {
                    "displayName": display_name,
                    "description": "Managed by the Onyx OneDrive fixture script",
                    "groupTypes": ["Unified"],
                    "mailEnabled": True,
                    "mailNickname": mail_nickname,
                    "securityEnabled": False,
                    "visibility": visibility.value,
                },
                GraphGroup,
            )
            group = GraphGroup.model_validate(result)

        self._set_exact_group_members(group.id, member_ids)
        return group

    def _set_exact_group_members(
        self, group_id: str, expected_member_ids: set[str]
    ) -> None:
        current = self._get_group_member_ids(group_id)
        additions, removals = exact_membership_changes(current, expected_member_ids)
        for member_id in removals:
            self.graph.delete(f"groups/{group_id}/members/{member_id}/$ref")
        for member_id in additions:
            self._add_group_member(group_id, member_id)

    def _get_group_member_ids(self, group_id: str) -> set[str]:
        for attempt in range(GROUP_PROVISION_ATTEMPTS):
            try:
                return {
                    GraphIdentity.model_validate(value).id
                    for value in self.graph.get_collection(
                        f"groups/{group_id}/members", {"$select": "id"}
                    )
                }
            except requests.HTTPError as error:
                if (
                    error.response is None
                    or error.response.status_code != 404
                    or attempt == GROUP_PROVISION_ATTEMPTS - 1
                ):
                    raise
                time.sleep(GROUP_PROVISION_POLL_SECONDS)
        raise RuntimeError(f"Timed out while waiting for fixture group {group_id}")

    def _add_group_member(self, group_id: str, member_id: str) -> None:
        for attempt in range(GROUP_PROVISION_ATTEMPTS):
            try:
                self.graph.post(
                    f"groups/{group_id}/members/$ref",
                    {
                        "@odata.id": (
                            f"{self.graph.base_url}/directoryObjects/{member_id}"
                        )
                    },
                )
                return
            except GraphFixtureError as error:
                if error.status_code != 404 or attempt == GROUP_PROVISION_ATTEMPTS - 1:
                    raise
                time.sleep(GROUP_PROVISION_POLL_SECONDS)

    def _apply_baseline_permissions(self, state: FixtureState) -> None:
        self._invite(
            state.drive.id, state.files[FilePath.DIRECT].id, state.primary_user.id
        )
        self._invite(
            state.drive.id,
            state.folders[FolderPath.INHERITED].id,
            state.primary_user.id,
        )
        self._invite(
            state.drive.id,
            state.files[FilePath.VISIBLE_GROUP].id,
            state.visible_group.id,
        )
        self._invite(
            state.drive.id,
            state.files[FilePath.HIDDEN_GROUP].id,
            state.hidden_group.id,
        )
        self._invite(
            state.drive.id,
            state.folders[FolderPath.MOVE_SOURCE].id,
            state.primary_user.id,
        )
        self._invite(
            state.drive.id,
            state.folders[FolderPath.MOVE_DESTINATION].id,
            state.alternate_user.id,
        )
        self._invite(
            state.drive.id,
            state.files[FilePath.REMOVE_SHARE].id,
            state.primary_user.id,
        )
        self._invite(
            state.drive.id,
            state.folders[FolderPath.RESTORE_PARENT].id,
            state.primary_user.id,
        )
        self._create_link(
            state.drive.id,
            state.files[FilePath.ANONYMOUS_LINK].id,
            LinkScope.ANONYMOUS,
        )
        self._create_link(
            state.drive.id,
            state.files[FilePath.ORGANIZATION_LINK].id,
            LinkScope.ORGANIZATION,
        )
        self._set_unique_access(
            state.site.web_url,
            state.drive.id,
            state.files[FilePath.RESTRICTED],
            {state.owner.user_principal_name, state.alternate_user.user_principal_name},
        )
        self._set_unique_access(
            state.site.web_url,
            state.drive.id,
            state.files[FilePath.RESTORE_INHERITANCE],
            {state.owner.user_principal_name, state.alternate_user.user_principal_name},
        )

    def _invite(self, drive_id: str, item_id: str, principal_id: str) -> None:
        self.graph.post(
            f"drives/{drive_id}/items/{item_id}/invite",
            {
                "recipients": [{"objectId": principal_id}],
                "requireSignIn": True,
                "sendInvitation": False,
                "roles": [SHARING_ROLE_READ],
                "retainInheritedPermissions": True,
            },
        )

    def _create_link(self, drive_id: str, item_id: str, scope: LinkScope) -> None:
        try:
            self.graph.post(
                f"drives/{drive_id}/items/{item_id}/createLink",
                {"type": "view", "scope": scope.value},
            )
        except GraphFixtureError as error:
            if (
                scope is not LinkScope.ANONYMOUS
                or error.status_code not in OPTIONAL_LINK_REJECTION_STATUSES
            ):
                raise
            logger.warning("Tenant policy rejected the optional anonymous-link fixture")

    def _set_unique_access(
        self,
        site_url: str,
        drive_id: str,
        item: GraphItem,
        user_principal_names: set[str],
    ) -> None:
        list_item = self._get_rest_list_item(site_url, drive_id, item)
        list_item.break_role_inheritance(
            copy_role_assignments=False, clear_sub_scopes=True
        ).execute_query()
        for user_principal_name in sorted(user_principal_names):
            context = list_item.context
            user = context.web.ensure_user(user_principal_name).execute_query()
            role = (
                context.web.role_definitions.get_by_name(READ_ROLE_NAME)
                .get()
                .execute_query()
            )
            list_item.role_assignments.add_role_assignment(
                user.id, role.id
            ).execute_query()

    def _reset_inheritance(self, site_url: str, drive_id: str, item: GraphItem) -> None:
        self._get_rest_list_item(
            site_url, drive_id, item
        ).reset_role_inheritance().execute_query()

    def _get_rest_list_item(
        self, site_url: str, drive_id: str, item: GraphItem
    ) -> ListItem:
        hydrated = GraphItem.model_validate(
            self.graph.get_model(
                f"drives/{drive_id}/items/{item.id}",
                GraphItem,
                {"$select": "id,name,webUrl,sharepointIds"},
            )
        )
        ids = hydrated.sharepoint_ids
        if not ids or not ids.list_id or not ids.list_item_id:
            raise RuntimeError(f"Missing SharePoint IDs for fixture item {item.name}")
        context = self._build_rest_context(site_url)
        return context.web.lists.get_by_id(ids.list_id).items.get_by_id(
            int(ids.list_item_id)
        )

    def _remove_principal_permissions(
        self, drive_id: str, item_id: str, principal_id: str
    ) -> None:
        permissions = [
            GraphPermission.model_validate(value)
            for value in self.graph.get_collection(
                f"drives/{drive_id}/items/{item_id}/permissions"
            )
        ]
        for permission in permissions:
            if permission.grants_principal(principal_id):
                self.graph.delete(
                    f"drives/{drive_id}/items/{item_id}/permissions/{permission.id}"
                )

    def _get_item_by_path(
        self, drive_id: str, path: FolderPath | FilePath
    ) -> GraphItem | None:
        return self._get_item_by_relative_path(drive_id, relative_to_fixture_root(path))

    def _require_item_by_path(
        self, drive_id: str, path: FolderPath | FilePath
    ) -> GraphItem:
        item = self._get_item_by_path(drive_id, path)
        if item is None:
            raise RuntimeError(f"Missing fixture item: {path.value}")
        return item

    def _get_item_by_relative_path(
        self, drive_id: str, relative_path: str
    ) -> GraphItem | None:
        encoded_path = quote(relative_path, safe="/")
        return self.graph.get_optional_item(
            f"drives/{drive_id}/root:/{encoded_path}?$select=id,name,webUrl,sharepointIds"
        )


def load_fixture_config() -> FixtureConfig:
    return FixtureConfig(
        owner_upn=os.environ.get(OWNER_UPN_ENV, DEFAULT_OWNER_UPN),
        second_owner_upn=os.environ.get(SECOND_OWNER_UPN_ENV, DEFAULT_SECOND_OWNER_UPN),
        primary_upn=os.environ.get(PRIMARY_UPN_ENV, DEFAULT_PRIMARY_UPN),
        alternate_upn=os.environ.get(ALTERNATE_UPN_ENV, DEFAULT_ALTERNATE_UPN),
    )


def load_certificate_credentials() -> CertificateAppCredentials:
    keys = [
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
    ]
    secrets = get_secrets(keys)
    missing = [key.name for key in keys if key not in secrets]
    if missing:
        raise RuntimeError(f"Missing required test secrets: {', '.join(missing)}")
    return CertificateAppCredentials(
        client_id=secrets[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        private_key=secrets[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        certificate_password=secrets[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
        directory_id=secrets[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
    )


def load_certificate_auth() -> tuple[MicrosoftAuthContext, Callable[[], str]]:
    credentials = load_certificate_credentials()
    auth = build_msal_app(
        client_id=credentials.client_id,
        directory_id=credentials.directory_id,
        authority_host=DEFAULT_AUTHORITY_HOST,
        auth_method=MicrosoftAuthMethod.CERTIFICATE,
        private_key_b64=credentials.private_key,
        certificate_password=credentials.certificate_password,
    )

    def get_access_token() -> str:
        response = acquire_graph_token(auth.app, DEFAULT_GRAPH_API_HOST)
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            error = response.get("error", "unknown")
            raise RuntimeError(f"Graph token acquisition failed: {error}")
        return access_token

    return auth, get_access_token


def build_provisioner(config: FixtureConfig) -> OneDriveFixtureProvisioner:
    auth, get_access_token = load_certificate_auth()
    graph = FixtureGraphClient(get_access_token, config.graph_api_host)

    def build_rest_context(site_url: str) -> ClientContext:
        tenant_name = site_url.split("://", 1)[1].split(".", 1)[0].removesuffix("-my")
        return ClientContext(site_url).with_access_token(
            lambda: acquire_token_for_rest(
                auth.app, tenant_name, DEFAULT_SHAREPOINT_DOMAIN_SUFFIX
            )
        )

    return OneDriveFixtureProvisioner(config, graph, build_rest_context)


def print_fixture_plan(phase: FixturePhase) -> None:
    print(f"Phase: {phase.value}")
    print(f"Fixture root: {FIXTURE_ROOT_NAME}")
    if phase is FixturePhase.SETUP:
        print(f"Folders: {len(FolderPath)}")
        print(f"Files: {len(FilePath)}")
        print("Setup deletes and recreates only the fixture root.")
    elif phase is FixturePhase.MUTATE:
        print("Mutations: move, unshare, restore inheritance, update, delete.")


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Provision the OneDrive connector test corpus"
    )
    parser.add_argument(
        "phase",
        type=FixturePhase,
        choices=list(FixturePhase),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply external changes. Without this flag, only print the plan.",
    )
    return CliArgs.model_validate(vars(parser.parse_args()))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    config = load_fixture_config()
    phase = args.phase
    print_fixture_plan(phase)
    if phase is FixturePhase.DESCRIBE or not args.apply:
        return

    provisioner = build_provisioner(config)
    if phase is FixturePhase.SETUP:
        state = provisioner.setup()
        print(f"Created fixture root with {len(state.files)} files.")
        return
    if phase is FixturePhase.MUTATE:
        provisioner.mutate()
        print("Applied fixture mutations.")


if __name__ == "__main__":
    main()
