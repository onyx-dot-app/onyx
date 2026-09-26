"""Typed Microsoft Graph drive delta pages and checkpoint-safe fetching."""

from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import quote, urljoin, urlsplit

import requests
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.utils.logger import setup_logger

logger = setup_logger()

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)
ODATA_VALUE_PROPERTY = "value"
ODATA_NEXT_LINK_PROPERTY = "@odata.nextLink"
ODATA_DELTA_LINK_PROPERTY = "@odata.deltaLink"
ODATA_REMOVED_PROPERTY = "@removed"
GRAPH_SHARED_CHANGED_PROPERTY = "@microsoft.graph.sharedChanged"
DRIVE_ITEM_ID_PROPERTY = "id"
DRIVE_ITEM_NAME_PROPERTY = "name"
DRIVE_ITEM_WEB_URL_PROPERTY = "webUrl"
DRIVE_ITEM_SIZE_PROPERTY = "size"
DRIVE_ITEM_FILE_PROPERTY = "file"
DRIVE_ITEM_FOLDER_PROPERTY = "folder"
DRIVE_ITEM_DELETED_PROPERTY = "deleted"
DRIVE_ITEM_SHARED_PROPERTY = "shared"
DRIVE_ITEM_CREATED_DATETIME_PROPERTY = "createdDateTime"
DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY = "lastModifiedDateTime"
DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY = "lastModifiedBy"
DRIVE_ITEM_PARENT_REFERENCE_PROPERTY = "parentReference"
SHAREPOINT_IDS_PROPERTY = "sharepointIds"
DRIVE_ITEM_DOWNLOAD_URL_PROPERTY = "@microsoft.graph.downloadUrl"
DRIVE_ITEM_DOWNLOAD_URL_SELECT = "content.downloadUrl"
DEFAULT_DRIVE_DELTA_PAGE_SIZE = 200

HTTP_GONE_STATUS = 410
LOCATION_HEADER = "Location"
PREFER_HEADER = "Prefer"
HIERARCHICAL_SHARING_PREFERENCE = "hierarchicalsharing"
SHOW_REMOVED_AS_DELETED_PREFERENCE = "deltashowremovedasdeleted"
TRAVERSE_PERMISSION_GAPS_PREFERENCE = "deltatraversepermissiongaps"
SHOW_SHARING_CHANGES_PREFERENCE = "deltashowsharingchanges"

DRIVE_DELTA_SELECT_FIELDS = ",".join(
    (
        DRIVE_ITEM_ID_PROPERTY,
        DRIVE_ITEM_NAME_PROPERTY,
        DRIVE_ITEM_WEB_URL_PROPERTY,
        DRIVE_ITEM_SIZE_PROPERTY,
        DRIVE_ITEM_FILE_PROPERTY,
        DRIVE_ITEM_FOLDER_PROPERTY,
        DRIVE_ITEM_DELETED_PROPERTY,
        DRIVE_ITEM_SHARED_PROPERTY,
        DRIVE_ITEM_CREATED_DATETIME_PROPERTY,
        DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY,
        DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY,
        DRIVE_ITEM_PARENT_REFERENCE_PROPERTY,
        SHAREPOINT_IDS_PROPERTY,
        DRIVE_ITEM_DOWNLOAD_URL_SELECT,
    )
)


class _GraphModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class DriveDeltaFileFacet(_GraphModel):
    mime_type: str | None = Field(default=None, alias="mimeType")


class DriveDeltaFolderFacet(_GraphModel):
    child_count: int | None = Field(default=None, alias="childCount")


class DriveDeltaDeletedFacet(_GraphModel):
    state: str | None = None


class DriveDeltaRemovedFacet(_GraphModel):
    reason: str | None = None


class DriveDeltaIdentity(_GraphModel):
    id: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    user_principal_name: str | None = Field(default=None, alias="userPrincipalName")


class DriveDeltaIdentitySet(_GraphModel):
    user: DriveDeltaIdentity | None = None
    application: DriveDeltaIdentity | None = None
    device: DriveDeltaIdentity | None = None


class DriveDeltaParentReference(_GraphModel):
    drive_id: str | None = Field(default=None, alias="driveId")
    drive_type: str | None = Field(default=None, alias="driveType")
    id: str | None = None
    name: str | None = None
    path: str | None = None
    site_id: str | None = Field(default=None, alias="siteId")


class GraphSharePointIds(_GraphModel):
    list_id: str | None = Field(default=None, alias="listId")
    list_item_id: str | None = Field(default=None, alias="listItemId")
    list_item_unique_id: str | None = Field(default=None, alias="listItemUniqueId")
    site_id: str | None = Field(default=None, alias="siteId")
    site_url: str | None = Field(default=None, alias="siteUrl")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    web_id: str | None = Field(default=None, alias="webId")


def parse_graph_sharepoint_ids(value: object) -> GraphSharePointIds | None:
    if not isinstance(value, dict):
        return None
    return GraphSharePointIds.model_validate(value)


class DriveDeltaSharingFacet(_GraphModel):
    scope: str | None = None
    shared_datetime: datetime | None = Field(default=None, alias="sharedDateTime")
    shared_by: DriveDeltaIdentitySet | None = Field(default=None, alias="sharedBy")
    owner: DriveDeltaIdentitySet | None = None


class DriveDeltaItem(_GraphModel):
    id: str
    name: str | None = None
    web_url: str | None = Field(default=None, alias=DRIVE_ITEM_WEB_URL_PROPERTY)
    size: int | None = None
    file: DriveDeltaFileFacet | None = None
    folder: DriveDeltaFolderFacet | None = None
    deleted: DriveDeltaDeletedFacet | None = None
    removed: DriveDeltaRemovedFacet | None = Field(
        default=None, alias=ODATA_REMOVED_PROPERTY
    )
    shared: DriveDeltaSharingFacet | None = None
    shared_changed: bool | None = Field(
        default=None, alias=GRAPH_SHARED_CHANGED_PROPERTY
    )
    created_datetime: datetime | None = Field(
        default=None, alias=DRIVE_ITEM_CREATED_DATETIME_PROPERTY
    )
    last_modified_datetime: datetime | None = Field(
        default=None, alias=DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY
    )
    last_modified_by: DriveDeltaIdentitySet | None = Field(
        default=None, alias=DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY
    )
    parent_reference: DriveDeltaParentReference | None = Field(
        default=None, alias=DRIVE_ITEM_PARENT_REFERENCE_PROPERTY
    )
    sharepoint_ids: Annotated[
        GraphSharePointIds | None, BeforeValidator(parse_graph_sharepoint_ids)
    ] = Field(default=None, alias=SHAREPOINT_IDS_PROPERTY)
    download_url: str | None = Field(
        default=None, alias=DRIVE_ITEM_DOWNLOAD_URL_PROPERTY
    )

    @property
    def is_file(self) -> bool:
        return self.file is not None

    @property
    def is_folder(self) -> bool:
        return self.folder is not None

    @property
    def is_tombstone(self) -> bool:
        return self.deleted is not None or self.removed is not None

    def to_graph_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class DriveDeltaPage(_GraphModel):
    items: list[DriveDeltaItem] = Field(
        default_factory=list, alias=ODATA_VALUE_PROPERTY
    )
    next_link: str | None = Field(default=None, alias=ODATA_NEXT_LINK_PROPERTY)
    delta_link: str | None = Field(default=None, alias=ODATA_DELTA_LINK_PROPERTY)


class DriveDeltaFetchResult(BaseModel):
    page: DriveDeltaPage
    next_checkpoint_url: str | None = None
    resync_after_410: bool = False


class DriveDeltaResyncPayload(_GraphModel):
    next_link: str | None = Field(default=None, alias=ODATA_NEXT_LINK_PROPERTY)
    delta_link: str | None = Field(default=None, alias=ODATA_DELTA_LINK_PROPERTY)


def build_onedrive_delta_request_headers() -> dict[str, str]:
    preferences = (
        HIERARCHICAL_SHARING_PREFERENCE,
        SHOW_REMOVED_AS_DELETED_PREFERENCE,
        TRAVERSE_PERMISSION_GAPS_PREFERENCE,
        SHOW_SHARING_CHANGES_PREFERENCE,
    )
    return {PREFER_HEADER: ", ".join(preferences)}


def build_delta_start_url(
    graph_api_base: str,
    drive_id: str,
    start: datetime | None = None,
    *,
    page_size: int = DEFAULT_DRIVE_DELTA_PAGE_SIZE,
    select_fields: str = DRIVE_DELTA_SELECT_FIELDS,
) -> str:
    params = [f"$top={page_size}", f"$select={select_fields}"]
    if start is not None and start > _EPOCH:
        params.append(f"token={quote(start.isoformat(timespec='seconds'))}")
    return f"{graph_api_base}/drives/{drive_id}/root/delta?{'&'.join(params)}"


def _same_delta_endpoint(candidate: str, expected: str) -> bool:
    try:
        candidate_parts = urlsplit(candidate)
        expected_parts = urlsplit(expected)
        candidate_port = candidate_parts.port
        expected_port = expected_parts.port
    except ValueError:
        return False
    return (
        candidate_parts.scheme == "https"
        and candidate_parts.username is None
        and candidate_parts.password is None
        and candidate_parts.hostname == expected_parts.hostname
        and candidate_port == expected_port
        and candidate_parts.path.rstrip("/") == expected_parts.path.rstrip("/")
        and not candidate_parts.fragment
    )


def _response_resync_candidates(response: requests.Response) -> list[str]:
    candidates = [response.headers.get(LOCATION_HEADER)]
    try:
        payload = DriveDeltaResyncPayload.model_validate(response.json())
    except (TypeError, ValueError):
        return [candidate for candidate in candidates if candidate]
    candidates.extend((payload.next_link, payload.delta_link))
    return [candidate for candidate in candidates if candidate]


def _trusted_resync_url(response: requests.Response, fallback: str) -> str:
    for candidate in _response_resync_candidates(response):
        absolute_candidate = urljoin(fallback, candidate)
        if _same_delta_endpoint(absolute_candidate, fallback):
            return absolute_candidate
    return fallback


def fetch_drive_delta_checkpoint_page(
    client: GraphApiClient,
    *,
    page_url: str,
    drive_id: str,
    request_headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    page_size: int = DEFAULT_DRIVE_DELTA_PAGE_SIZE,
    select_fields: str = DRIVE_DELTA_SELECT_FIELDS,
    allow_full_resync: bool = True,
) -> DriveDeltaFetchResult:
    """Fetch one page and return the exact cursor the caller can checkpoint."""
    try:
        data = client.get_json(page_url, query_params, request_headers)
    except requests.HTTPError as error:
        response = error.response
        if (
            response is None
            or response.status_code != HTTP_GONE_STATUS
            or not allow_full_resync
        ):
            raise

        fallback = build_delta_start_url(
            client.graph_api_base,
            drive_id,
            page_size=page_size,
            select_fields=select_fields,
        )
        resync_url = _trusted_resync_url(response, fallback)
        logger.warning(
            "Delta token expired for drive '%s'; restarting full enumeration",
            drive_id,
        )
        return DriveDeltaFetchResult(
            page=DriveDeltaPage(),
            next_checkpoint_url=resync_url,
            resync_after_410=True,
        )

    page = DriveDeltaPage.model_validate(data)
    return DriveDeltaFetchResult(
        page=page,
        next_checkpoint_url=page.next_link,
    )
