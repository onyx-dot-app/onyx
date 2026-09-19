"""Read-only access to the fixed OneDrive tenant corpus."""

import os
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar
from urllib.parse import quote

import requests
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthMethod,
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from tests.utils.aws_secrets import get_secrets
from tests.utils.secret_names import TestSecret

GROUP_OWNERSHIP_MARKER_PREFIX = "onyx-fixture-owner:"
DAILY_FIXTURE_OWNER = "onedrive-daily-v1"
INTEGRATION_FIXTURE_OWNER = "onedrive-integration-v1"
DAILY_FIXTURE_ROOT_NAME = "Onyx OneDrive Daily Tests"
INTEGRATION_FIXTURE_ROOT_NAME = "Onyx OneDrive Integration Tests"
VISIBLE_GROUP_NAME = "Onyx OneDrive Visible Test Group"
VISIBLE_GROUP_ALIAS = "onyx-onedrive-visible-test"
HIDDEN_GROUP_NAME = "Onyx OneDrive Hidden Test Group"
HIDDEN_GROUP_ALIAS = "onyx-onedrive-hidden-test"
DEFAULT_OWNER_UPN = "test@danswerai.onmicrosoft.com"
DEFAULT_PRIMARY_UPN = "subash@onyx.app"
DEFAULT_SECOND_OWNER_UPN = DEFAULT_PRIMARY_UPN
DEFAULT_ALTERNATE_UPN = "raunak@onyx.app"
DEFAULT_FIXTURE_OWNER = "onedrive-spike-v1"
FIXTURE_ROOT_NAME = "Onyx OneDrive Connector Tests"
IDENTITY_FOLDER_NAME = "90-identity"
IDENTITY_FILE_NAME = "cross-drive-duplicate.docx"
GRAPH_API_VERSION = "v1.0"

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


FIXTURE_EXCLUDED_PATHS = [
    FilePath.EXCLUDED.value.rsplit("/", 1)[-1],
    FilePath.OVER_SIZE.value.rsplit("/", 1)[-1],
    "*.test-extension",
]


class GroupVisibility(str, Enum):
    PRIVATE = "Private"
    HIDDEN_MEMBERSHIP = "HiddenMembership"


class LinkScope(str, Enum):
    ANONYMOUS = "anonymous"
    ORGANIZATION = "organization"


class AnonymousLinkOutcome(str, Enum):
    CREATED = "created"
    REJECTED_BY_TENANT_POLICY = "rejected_by_tenant_policy"


ANONYMOUS_LINK_SKIP_REASON = (
    "The tenant policy does not permit anonymous sharing links."
)


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
    description: str | None = None
    visibility: str | None = None


class GraphSharingLink(BaseModel):
    scope: LinkScope


class GraphPermission(BaseModel):
    link: GraphSharingLink | None = None


class GraphCollection(BaseModel):
    value: list[dict[str, Any]]
    next_link: str | None = Field(default=None, alias="@odata.nextLink")


class FixtureGroupConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    display_name: str
    mail_nickname: str
    visibility: GroupVisibility


class FixtureCorpusConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    root_name: str
    owner_marker: str
    visible_group: FixtureGroupConfig
    hidden_group: FixtureGroupConfig

    @property
    def ownership_description(self) -> str:
        return f"{GROUP_OWNERSHIP_MARKER_PREFIX}{self.owner_marker}"


def _fixture_corpus_config(
    *,
    root_name: str,
    owner_marker: str,
    group_name_suffix: str = "",
) -> FixtureCorpusConfig:
    alias_suffix = "" if owner_marker == DEFAULT_FIXTURE_OWNER else f"-{owner_marker}"
    return FixtureCorpusConfig(
        root_name=root_name,
        owner_marker=owner_marker,
        visible_group=FixtureGroupConfig(
            display_name=f"{VISIBLE_GROUP_NAME}{group_name_suffix}",
            mail_nickname=f"{VISIBLE_GROUP_ALIAS}{alias_suffix}",
            visibility=GroupVisibility.PRIVATE,
        ),
        hidden_group=FixtureGroupConfig(
            display_name=f"{HIDDEN_GROUP_NAME}{group_name_suffix}",
            mail_nickname=f"{HIDDEN_GROUP_ALIAS}{alias_suffix}",
            visibility=GroupVisibility.HIDDEN_MEMBERSHIP,
        ),
    )


DEFAULT_CORPUS_CONFIG = _fixture_corpus_config(
    root_name=FIXTURE_ROOT_NAME,
    owner_marker=DEFAULT_FIXTURE_OWNER,
)
DAILY_CORPUS_CONFIG = _fixture_corpus_config(
    root_name=DAILY_FIXTURE_ROOT_NAME,
    owner_marker=DAILY_FIXTURE_OWNER,
    group_name_suffix=" (Daily)",
)
INTEGRATION_CORPUS_CONFIG = _fixture_corpus_config(
    root_name=INTEGRATION_FIXTURE_ROOT_NAME,
    owner_marker=INTEGRATION_FIXTURE_OWNER,
    group_name_suffix=" (Integration)",
)


class FixtureConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner_upn: str = DEFAULT_OWNER_UPN
    second_owner_upn: str = DEFAULT_SECOND_OWNER_UPN
    primary_upn: str = DEFAULT_PRIMARY_UPN
    alternate_upn: str = DEFAULT_ALTERNATE_UPN
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
    authority_host: str = DEFAULT_AUTHORITY_HOST
    corpus: FixtureCorpusConfig = DEFAULT_CORPUS_CONFIG


class CertificateAppCredentials(BaseModel):
    client_id: str
    private_key: str
    certificate_password: str
    directory_id: str


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
    anonymous_link_outcome: AnonymousLinkOutcome


GraphModel = TypeVar("GraphModel", bound=BaseModel)


class FixtureGraphReader(GraphApiClient):
    def __init__(
        self, get_access_token: Callable[[], str], graph_api_host: str
    ) -> None:
        base_url = f"{graph_api_host.rstrip('/')}/{GRAPH_API_VERSION}"
        super().__init__(get_access_token, base_url)
        self.base_url = base_url

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
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
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

    def _url(self, path: str) -> str:
        return (
            path
            if path.startswith("https://")
            else f"{self.base_url}/{path.lstrip('/')}"
        )


class OneDriveFixtureReader:
    def __init__(self, config: FixtureConfig, graph: FixtureGraphReader) -> None:
        self.config = config
        self.graph = graph

    def load_state(self) -> FixtureState:
        owner = self._get_user(self.config.owner_upn)
        second_owner = self._get_user(self.config.second_owner_upn)
        primary_user = self._get_user(self.config.primary_upn)
        alternate_user = self._get_user(self.config.alternate_upn)
        drive = self._get_drive(owner.id)
        second_drive = self._get_drive(second_owner.id)
        site = self._get_drive_site(drive)
        root_item = self._require_item_by_relative_path(
            drive.id, self.config.corpus.root_name
        )
        folders = {
            path: self._require_item_by_path(drive.id, path) for path in FolderPath
        }
        files = {
            path: self._require_item_by_path(drive.id, path)
            for path in FilePath
            if path is not FilePath.MOVE_DESTINATION
        }
        second_drive_duplicate = self._require_item_by_path(
            second_drive.id, FilePath.IDENTITY
        )
        anonymous_outcome = self._anonymous_link_outcome(
            drive.id, files[FilePath.ANONYMOUS_LINK].id
        )
        return FixtureState(
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
            visible_group=self._load_group(self.config.corpus.visible_group),
            hidden_group=self._load_group(self.config.corpus.hidden_group),
            second_drive_duplicate=second_drive_duplicate,
            anonymous_link_outcome=anonymous_outcome,
        )

    def _get_user(self, upn: str) -> GraphUser:
        return self.graph.get_model(
            f"users/{quote(upn, safe='')}",
            GraphUser,
            {"$select": "id,userPrincipalName"},
        )

    def _get_drive(self, user_id: str) -> GraphDrive:
        return self.graph.get_model(
            f"users/{user_id}/drive",
            GraphDrive,
            {"$select": "id,name,driveType,webUrl,sharepointIds"},
        )

    def _get_drive_root(self, drive_id: str) -> GraphItem:
        return self.graph.get_model(
            f"drives/{drive_id}/root",
            GraphItem,
            {"$select": "id,name,webUrl,sharepointIds"},
        )

    def _get_drive_site(self, drive: GraphDrive) -> GraphSite:
        site_id = drive.sharepoint_ids.site_id if drive.sharepoint_ids else None
        if site_id is None:
            root_ids = self._get_drive_root(drive.id).sharepoint_ids
            site_id = root_ids.site_id if root_ids else None
        if not site_id:
            raise RuntimeError("The test drive did not return a SharePoint site ID")
        return self.graph.get_model(
            f"sites/{site_id}", GraphSite, {"$select": "id,webUrl"}
        )

    def _load_group(self, group_config: FixtureGroupConfig) -> GraphGroup:
        escaped_alias = group_config.mail_nickname.replace("'", "''")
        matches = self.graph.get_collection(
            "groups",
            {
                "$filter": f"mailNickname eq '{escaped_alias}'",
                "$select": "id,displayName,mailNickname,description,visibility",
            },
        )
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one fixture group with alias {group_config.mail_nickname}"
            )
        group = GraphGroup.model_validate(matches[0])
        if group.description != self.config.corpus.ownership_description:
            raise RuntimeError(
                f"Unexpected fixture group: {group_config.mail_nickname}"
            )
        if group.visibility != group_config.visibility.value:
            raise RuntimeError(
                f"Unexpected fixture group visibility: {group_config.mail_nickname}"
            )
        return group

    def _anonymous_link_outcome(
        self, drive_id: str, item_id: str
    ) -> AnonymousLinkOutcome:
        permissions = [
            GraphPermission.model_validate(value)
            for value in self.graph.get_collection(
                f"drives/{drive_id}/items/{item_id}/permissions"
            )
        ]
        if any(
            permission.link is not None and permission.link.scope is LinkScope.ANONYMOUS
            for permission in permissions
        ):
            return AnonymousLinkOutcome.CREATED
        return AnonymousLinkOutcome.REJECTED_BY_TENANT_POLICY

    def _require_item_by_path(
        self, drive_id: str, path: FolderPath | FilePath
    ) -> GraphItem:
        relative_path = f"{self.config.corpus.root_name}/{path.value}"
        return self._require_item_by_relative_path(drive_id, relative_path)

    def _require_item_by_relative_path(
        self, drive_id: str, relative_path: str
    ) -> GraphItem:
        encoded_path = quote(relative_path, safe="/")
        item = self.graph.get_optional_item(
            f"drives/{drive_id}/root:/{encoded_path}"
            "?$select=id,name,webUrl,sharepointIds"
        )
        if item is None:
            raise RuntimeError(f"Missing fixture item: {relative_path}")
        return item


def load_fixture_config(
    corpus: FixtureCorpusConfig = DEFAULT_CORPUS_CONFIG,
) -> FixtureConfig:
    return FixtureConfig(
        owner_upn=os.environ.get(OWNER_UPN_ENV, DEFAULT_OWNER_UPN),
        second_owner_upn=os.environ.get(SECOND_OWNER_UPN_ENV, DEFAULT_SECOND_OWNER_UPN),
        primary_upn=os.environ.get(PRIMARY_UPN_ENV, DEFAULT_PRIMARY_UPN),
        alternate_upn=os.environ.get(ALTERNATE_UPN_ENV, DEFAULT_ALTERNATE_UPN),
        corpus=corpus,
    )


def build_daily_fixture_config() -> FixtureConfig:
    return load_fixture_config(DAILY_CORPUS_CONFIG)


def build_integration_fixture_config() -> FixtureConfig:
    return load_fixture_config(INTEGRATION_CORPUS_CONFIG)


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


def build_fixture_reader(config: FixtureConfig) -> OneDriveFixtureReader:
    credentials = load_certificate_credentials()
    auth = build_msal_app(
        client_id=credentials.client_id,
        directory_id=credentials.directory_id,
        authority_host=config.authority_host,
        auth_method=MicrosoftAuthMethod.CERTIFICATE,
        private_key_b64=credentials.private_key,
        certificate_password=credentials.certificate_password,
    )

    def get_access_token() -> str:
        response = acquire_graph_token(auth.app, config.graph_api_host)
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            error = response.get("error", "unknown")
            raise RuntimeError(f"Graph token acquisition failed: {error}")
        return access_token

    return OneDriveFixtureReader(
        config,
        FixtureGraphReader(get_access_token, config.graph_api_host),
    )
