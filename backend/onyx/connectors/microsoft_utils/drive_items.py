"""Graph driveItem handling shared by the file-bearing Microsoft connectors.

Covers the item model, the delta and folder walks, the time-window filter, the
size-capped download and the extraction of an item's bytes into Onyx sections.
Assembling the final ``Document`` stays with each connector, because the source,
the permission lookup and the metadata are the connector's identity.
"""

import fnmatch
import io
import time
from collections import deque
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests
from office365.graph_client import GraphClient
from office365.onedrive.driveitems.driveItem import DriveItem
from office365.runtime.paths.resource_path import ResourcePath
from pydantic import BaseModel

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    extract_and_stage_tabular_file,
    is_tabular_file,
)
from onyx.connectors.microsoft_utils.graph_client import (
    TRANSIENT_TRANSPORT_EXCEPTIONS,
    GraphApiClient,
    backoff_seconds,
    log_and_raise_for_status,
)
from onyx.connectors.models import ImageSection, TabularSection, TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions, OnyxMimeTypes
from onyx.file_processing.image_utils import (
    make_image_callback,
    store_image_and_create_section,
)
from onyx.file_store.staging import RawFileCallback
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger

logger = setup_logger()

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)

SHAREPOINT_IDS_PROPERTY = "sharepointIds"
LIST_ITEM_ID_PROPERTY = "listItemId"
DRIVE_ITEM_ID_PROPERTY = "id"
DRIVE_ITEM_NAME_PROPERTY = "name"
DRIVE_ITEM_WEB_URL_PROPERTY = "webUrl"
DRIVE_ITEM_SIZE_PROPERTY = "size"
DRIVE_ITEM_FILE_PROPERTY = "file"
DRIVE_ITEM_CREATED_DATETIME_PROPERTY = "createdDateTime"
DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY = "lastModifiedDateTime"
DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY = "lastModifiedBy"
DRIVE_ITEM_PARENT_REFERENCE_PROPERTY = "parentReference"
DRIVE_ITEM_FOLDER_PROPERTY = "folder"
DRIVE_ITEM_DELETED_PROPERTY = "deleted"
DRIVE_ITEM_DOWNLOAD_URL_PROPERTY = "@microsoft.graph.downloadUrl"
DRIVE_ITEM_DOWNLOAD_URL_SELECT = "content.downloadUrl"
DRIVE_ITEM_SELECT_FIELDS = ",".join(
    (
        DRIVE_ITEM_ID_PROPERTY,
        DRIVE_ITEM_NAME_PROPERTY,
        DRIVE_ITEM_WEB_URL_PROPERTY,
        DRIVE_ITEM_SIZE_PROPERTY,
        DRIVE_ITEM_FILE_PROPERTY,
        DRIVE_ITEM_CREATED_DATETIME_PROPERTY,
        DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY,
        DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY,
        DRIVE_ITEM_PARENT_REFERENCE_PROPERTY,
        SHAREPOINT_IDS_PROPERTY,
        DRIVE_ITEM_FOLDER_PROPERTY,
        DRIVE_ITEM_DELETED_PROPERTY,
        DRIVE_ITEM_DOWNLOAD_URL_SELECT,
    )
)

# Graph closes the connection mid-body under throttling, so a streaming
# download retries transport errors on top of its initial attempt.
STREAM_DOWNLOAD_MAX_RETRIES = 3
STREAM_CHUNK_SIZE = 64 * 1024


class SizeCapExceeded(Exception):
    """Exception raised when the size cap is exceeded."""


class DriveItemContentError(Exception):
    """An item's content could not be retrieved or extracted.

    Callers turn this into their own source-prefixed ``ConnectorFailure`` so a
    single bad file never fails the run.
    """


def parse_graph_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a Graph datetime that may be an ISO string or datetime."""
    if not value:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"Unsupported Graph datetime value: {value!r}")
    # Graph timestamps are UTC. A naive value would not compare with aware bounds.
    return datetime_to_utc(parsed)


def timestamp_in_window(
    timestamp: datetime,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    return (start is None or timestamp >= start) and (end is None or timestamp <= end)


def drive_item_in_time_window(
    item: dict[str, Any],
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Return True if a drive item falls within [start, end].

    Uses the later of `createdDateTime` and `lastModifiedDateTime`, or whichever
    is present: a file copied or synced into a drive keeps its original
    modification date, which can predate the window even though the file is new
    to the drive. Items carrying neither timestamp are kept.

    Checking only the latest change attributes each item to exactly one poll
    window. A change after `end` lands in the next window, which starts
    POLL_CONNECTOR_OFFSET before this one ends.
    """
    if start is None and end is None:
        return True

    timestamps = [
        ts
        for ts in (
            parse_graph_datetime(item.get(DRIVE_ITEM_CREATED_DATETIME_PROPERTY)),
            parse_graph_datetime(item.get(DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY)),
        )
        if ts is not None
    ]
    if not timestamps:
        return True

    return timestamp_in_window(max(timestamps), start, end)


def is_path_excluded(item_path: str, excluded_path_patterns: list[str]) -> bool:
    """Check if a drive item path matches any of the exclusion glob patterns.

    item_path is the relative path within a drive, e.g. "Engineering/API/report.docx".
    Matches are attempted against the full path and the filename alone so that
    patterns like "*.tmp" match files at any depth.
    """
    filename = item_path.rsplit("/", 1)[-1] if "/" in item_path else item_path
    for pattern in excluded_path_patterns:
        if fnmatch.fnmatch(item_path, pattern) or fnmatch.fnmatch(filename, pattern):
            return True
    return False


def build_item_relative_path(parent_reference_path: str | None, item_name: str) -> str:
    """Build the relative path of a drive item from its parentReference.path and name.

    Example: parentReference.path="/drives/abc/root:/Eng/API", name="report.docx"
    => "Eng/API/report.docx"
    """
    if parent_reference_path and "root:/" in parent_reference_path:
        folder = unquote(parent_reference_path.split("root:/", 1)[1])
        if folder:
            return f"{folder}/{item_name}"
    return item_name


def extract_folder_path_from_parent_reference(
    parent_reference_path: str | None,
) -> str | None:
    """Extract folder path from DriveItem's parentReference.path.

    Example input: "/drives/b!abc123/root:/Engineering/API"
    Example output: "Engineering/API"

    Stays percent-encoded because the result becomes a hierarchy node id.

    Returns None if the item is at the root of the drive.
    """
    if not parent_reference_path:
        return None

    # Path format: /drives/{drive_id}/root:/folder/path
    if "root:/" in parent_reference_path:
        folder_path = parent_reference_path.split("root:/")[1]
        return folder_path if folder_path else None

    # Item is at drive root
    return None


class DriveItemData(BaseModel):
    """Lightweight representation of a Graph API drive item, parsed from JSON.

    Replaces the SDK DriveItem for fetching/listing so that we can paginate
    lazily through the Graph API without materialising every item in memory.
    """

    id: str
    name: str
    web_url: str
    size: int | None = None
    mime_type: str | None = None
    download_url: str | None = None
    created_datetime: datetime | None = None
    last_modified_datetime: datetime | None = None
    last_modified_by_display_name: str | None = None
    last_modified_by_email: str | None = None
    parent_reference_path: str | None = None
    drive_id: str | None = None
    list_item_id: str | None = None

    @classmethod
    def from_graph_json(cls, item: dict[str, Any]) -> "DriveItemData":
        last_modified_by = item.get(DRIVE_ITEM_LAST_MODIFIED_BY_PROPERTY, {}).get(
            "user", {}
        )
        parent_ref = item.get(DRIVE_ITEM_PARENT_REFERENCE_PROPERTY, {})
        sharepoint_ids = item.get(SHAREPOINT_IDS_PROPERTY) or {}

        return cls(
            id=item[DRIVE_ITEM_ID_PROPERTY],
            name=item.get(DRIVE_ITEM_NAME_PROPERTY, ""),
            web_url=item.get(DRIVE_ITEM_WEB_URL_PROPERTY, ""),
            size=item.get(DRIVE_ITEM_SIZE_PROPERTY),
            mime_type=item.get(DRIVE_ITEM_FILE_PROPERTY, {}).get("mimeType"),
            download_url=item.get(DRIVE_ITEM_DOWNLOAD_URL_PROPERTY),
            created_datetime=parse_graph_datetime(
                item.get(DRIVE_ITEM_CREATED_DATETIME_PROPERTY)
            ),
            last_modified_datetime=parse_graph_datetime(
                item.get(DRIVE_ITEM_LAST_MODIFIED_DATETIME_PROPERTY)
            ),
            last_modified_by_display_name=last_modified_by.get("displayName"),
            last_modified_by_email=(
                last_modified_by.get("email")
                or last_modified_by.get("userPrincipalName")
            ),
            parent_reference_path=parent_ref.get("path"),
            drive_id=parent_ref.get("driveId"),
            list_item_id=sharepoint_ids.get(LIST_ITEM_ID_PROPERTY),
        )

    def to_sdk_driveitem(self, graph_client: GraphClient) -> DriveItem:
        """Construct a lazy SDK DriveItem for permission lookups."""
        if not self.drive_id:
            raise ValueError("drive_id is required to construct SDK DriveItem")
        path = ResourcePath(
            self.id,
            ResourcePath("items", ResourcePath(self.drive_id, ResourcePath("drives"))),
        )
        item = DriveItem(graph_client, path)
        item.set_property("id", self.id)
        if self.list_item_id:
            item.set_property(
                SHAREPOINT_IDS_PROPERTY,
                {LIST_ITEM_ID_PROPERTY: self.list_item_id},
            )
        return item


class DriveItemContent(BaseModel):
    """An item's extracted sections, ready for a connector to wrap in a Document."""

    sections: list[TextSection | ImageSection | TabularSection]
    # Only tabular files carry a `file_id` on the Document
    staged_file_id: str | None = None


def redact_url_for_logging(url: str, max_len: int = 120) -> str:
    """Return a log-safe identifier for a URL.

    Microsoft's ``@microsoft.graph.downloadUrl`` is a pre-authenticated link
    whose query string carries a ``tempauth=`` JWT (and similar credential
    parameters). Logging the raw URL — even truncated — can leak a working
    download credential into log aggregators. Strip query and fragment, keep
    just ``scheme://host/path`` truncated to ``max_len`` for grep-ability.
    """
    parts = urlsplit(url)
    safe = f"{parts.scheme}://{parts.netloc}{parts.path}"
    if len(safe) > max_len:
        safe = safe[:max_len] + "..."
    return safe


def probe_remote_size(url: str, timeout: int) -> int | None:
    """Determine remote size using HEAD or a range GET probe. Returns None if unknown."""
    try:
        head_resp = requests.head(url, timeout=timeout, allow_redirects=True)
        log_and_raise_for_status(head_resp)
        cl = head_resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            return int(cl)
    except requests.RequestException:
        pass

    # Fallback: Range request for first byte to read total from Content-Range
    try:
        with requests.get(
            url,
            headers={"Range": "bytes=0-0"},
            timeout=timeout,
            stream=True,
        ) as range_resp:
            log_and_raise_for_status(range_resp)
            cr = range_resp.headers.get("Content-Range")  # e.g., "bytes 0-0/12345"
            if cr and "/" in cr:
                total = cr.split("/")[-1]
                if total.isdigit():
                    return int(total)
    except requests.RequestException:
        pass

    # If both HEAD and a range GET failed to reveal a size, signal unknown size.
    # Callers should treat None as "size unavailable" and proceed with a safe
    # streaming path that enforces a hard cap to avoid excessive memory usage.
    return None


def stream_response_to_buffer_with_cap(
    request_factory: Callable[[], requests.Response],
    cap: int,
    description: str,
    max_retries: int = STREAM_DOWNLOAD_MAX_RETRIES,
) -> bytes:
    """Stream a GET response into memory with a byte cap, retrying on transient
    transport-level failures.

    SharePoint / Graph occasionally drop the TCP connection mid-body (surfaces
    as `ChunkedEncodingError: IncompleteRead`). Each retry calls
    ``request_factory`` again to obtain a fresh ``Response`` -- this also
    avoids reusing a stale socket from urllib3's connection pool.

    Args:
        request_factory: Zero-arg callable that issues a streaming GET and
            returns the ``requests.Response``. Called once per attempt.
        cap: Maximum number of bytes to read before raising ``SizeCapExceeded``.
        description: Short label used in log messages.
        max_retries: Number of retries beyond the initial attempt.

    Raises:
        SizeCapExceeded: when ``cap`` is exceeded (never retried).
        requests.RequestException: when retries are exhausted; HTTPError from
            ``raise_for_status`` is not retried here.
    """
    for attempt in range(max_retries + 1):
        try:
            with request_factory() as resp:
                log_and_raise_for_status(resp)

                cl_header = resp.headers.get("Content-Length")
                if cl_header and cl_header.isdigit() and int(cl_header) > cap:
                    logger.warning(
                        "Content-Length %s exceeds cap %s for %s; skipping download.",
                        cl_header,
                        cap,
                        description,
                    )
                    raise SizeCapExceeded("pre_download")

                buf = io.BytesIO()
                for chunk in resp.iter_content(STREAM_CHUNK_SIZE):
                    if not chunk:
                        continue
                    buf.write(chunk)
                    if buf.tell() > cap:
                        logger.warning(
                            "Streaming download for %s exceeded cap %s bytes; "
                            "aborting early.",
                            description,
                            cap,
                        )
                        raise SizeCapExceeded("during_download")
                return buf.getvalue()
        except TRANSIENT_TRANSPORT_EXCEPTIONS as e:
            if attempt >= max_retries:
                logger.warning(
                    "Streaming download for %s failed after %s attempts: %s: %s",
                    description,
                    max_retries + 1,
                    type(e).__name__,
                    e,
                )
                raise
            sleep_time = backoff_seconds(attempt, retry_after=None)
            logger.warning(
                "Streaming download for %s hit transport error on attempt %s/%s: "
                "%s: %s. Sleeping %.1fs before retry.",
                description,
                attempt + 1,
                max_retries + 1,
                type(e).__name__,
                e,
                sleep_time,
            )
            time.sleep(sleep_time)

    # Defensive: the loop either returns or re-raises on the final attempt.
    raise RuntimeError(
        f"Unreachable: streaming download retry loop exited without resolution "
        f"for {description}"
    )


def download_with_cap(url: str, timeout: int, cap: int) -> bytes:
    """Stream download content with an upper bound on bytes read.

    Behavior:
    - Checks `Content-Length` first and aborts early if it exceeds `cap`.
    - Otherwise streams the body in chunks and stops once `cap` is surpassed.
    - Retries on transient transport errors (e.g. mid-stream connection drops).
    - Raises `SizeCapExceeded` when the cap would be exceeded.
    - Returns the full bytes if the content fits within `cap`.
    """

    def _factory() -> requests.Response:
        return requests.get(url, stream=True, timeout=timeout)

    return stream_response_to_buffer_with_cap(
        _factory, cap, description=f"downloadUrl:{redact_url_for_logging(url)}"
    )


def download_via_graph_api(
    access_token: str,
    drive_id: str,
    item_id: str,
    bytes_allowed: int,
    graph_api_base: str,
) -> bytes:
    """Download a drive item via the Graph API /content endpoint with a byte cap.

    Retries on transient transport errors. Raises SizeCapExceeded if the cap is
    exceeded.
    """
    url = f"{graph_api_base}/drives/{drive_id}/items/{item_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}

    def _factory() -> requests.Response:
        return requests.get(
            url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT_SECONDS
        )

    return stream_response_to_buffer_with_cap(
        _factory,
        bytes_allowed,
        description=f"graph_api(drive={drive_id},item={item_id})",
    )


def extract_drive_item_content(
    driveitem: DriveItemData,
    size_threshold: int,
    graph_api_base: str,
    access_token: str | None = None,
    raw_file_callback: RawFileCallback | None = None,
) -> DriveItemContent | None:
    """Download an item and extract it into Onyx sections.

    Returns None when the item should be skipped (excluded mime type, over the
    size threshold, or a download that hit the cap). Raises
    ``DriveItemContentError`` when the item failed and the caller should record
    a document failure.
    """
    if not driveitem.name or not driveitem.id:
        raise ValueError("DriveItem name/id is required")

    mime_type = driveitem.mime_type
    if not mime_type or mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
        logger.debug(
            "Skipping malformed or excluded mime type %s for %s",
            mime_type,
            driveitem.name,
        )
        return None

    file_size = driveitem.size
    download_url = driveitem.download_url

    if file_size is None and download_url:
        file_size = probe_remote_size(download_url, REQUEST_TIMEOUT_SECONDS)

    if file_size is not None and file_size > size_threshold:
        logger.warning(
            "Skipping '%s' over size threshold (%s > %s bytes).",
            driveitem.name,
            file_size,
            size_threshold,
        )
        return None

    # Prefer downloadUrl streaming with size cap
    content_bytes: bytes | None = None
    if download_url:
        try:
            content_bytes = download_with_cap(
                download_url,
                REQUEST_TIMEOUT_SECONDS,
                size_threshold,
            )
        except SizeCapExceeded as e:
            logger.warning(
                "Skipping '%s' exceeded size cap: %s", driveitem.name, str(e)
            )
            return None
        except requests.RequestException as e:
            status = e.response.status_code if e.response is not None else -1
            logger.warning(
                "Failed to download via downloadUrl for '%s' (status=%s); falling back to Graph API.",
                driveitem.name,
                status,
            )

    # Fallback: download via Graph API /content endpoint
    if content_bytes is None and access_token and driveitem.drive_id:
        try:
            content_bytes = download_via_graph_api(
                access_token,
                driveitem.drive_id,
                driveitem.id,
                size_threshold,
                graph_api_base=graph_api_base,
            )
        except SizeCapExceeded:
            logger.warning(
                "Skipping '%s' exceeded size cap during Graph API download.",
                driveitem.name,
            )
            return None
        except Exception as e:
            logger.warning(
                "Failed to download via Graph API for '%s': %s", driveitem.name, e
            )
            raise DriveItemContentError(f"Failed to download via graph api: {e}") from e

    sections: list[TextSection | ImageSection | TabularSection] = []
    staged_file_id: str | None = None
    file_ext = get_file_ext(driveitem.name)

    if not content_bytes:
        logger.warning(
            "Zero-length content for '%s'. Skipping text/image extraction.",
            driveitem.name,
        )
    elif file_ext in OnyxFileExtensions.IMAGE_EXTENSIONS:
        image_section, _ = store_image_and_create_section(
            image_data=content_bytes,
            file_id=driveitem.id,
            display_name=driveitem.name,
            file_origin=FileOrigin.CONNECTOR,
        )
        image_section.link = driveitem.web_url
        sections.append(image_section)
    elif is_tabular_file(driveitem.name):
        # Tabular content is always staged via the callback. Without it we
        # cannot produce the section, so fail the item rather than emit an
        # empty-section Document that could overwrite indexed content.
        if raw_file_callback is None:
            raise DriveItemContentError(
                f"raw_file_callback not set; cannot stage tabular file {driveitem.name}"
            )
        try:
            result = extract_and_stage_tabular_file(
                file=io.BytesIO(content_bytes),
                file_name=driveitem.name,
                content_type=mime_type or "application/octet-stream",
                raw_file_callback=raw_file_callback,
                link=driveitem.web_url or "",
            )
            sections.extend(result.sections)
            staged_file_id = result.staged_file_id
        except Exception as e:
            raise DriveItemContentError(
                f"Failed to extract tabular sections for {driveitem.name}: {e}"
            ) from e
    else:
        extraction_result = extract_text_and_images(
            file=io.BytesIO(content_bytes),
            file_name=driveitem.name,
            image_callback=make_image_callback(
                sections, driveitem.id, driveitem.name, driveitem.web_url
            ),
        )
        if extraction_result.text_content:
            sections.append(
                TextSection(link=driveitem.web_url, text=extraction_result.text_content)
            )

    return DriveItemContent(sections=sections, staged_file_id=staged_file_id)


def iter_drive_items_paged(
    client: GraphApiClient,
    drive_id: str,
    folder_path: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page_size: int = 200,
) -> Generator[DriveItemData, None, None]:
    """Yield DriveItemData for every file in a drive via the Graph API.

    Performs BFS folder traversal manually, fetching one page of children
    at a time so that memory usage stays bounded regardless of drive size.
    """
    base = f"{client.graph_api_base}/drives/{drive_id}"
    if folder_path:
        encoded_path = quote(folder_path, safe="/")
        start_url = f"{base}/root:/{encoded_path}:/children"
    else:
        start_url = f"{base}/root/children"

    folder_queue: deque[str] = deque([start_url])

    while folder_queue:
        page_url: str | None = folder_queue.popleft()
        params: dict[str, str] | None = {
            "$top": str(page_size),
            "$select": DRIVE_ITEM_SELECT_FIELDS,
        }

        while page_url:
            data = client.get_json(page_url, params)
            params = None  # nextLink already embeds query params

            for item in data.get("value", []):
                if DRIVE_ITEM_FOLDER_PROPERTY in item:
                    child_url = f"{base}/items/{item[DRIVE_ITEM_ID_PROPERTY]}/children"
                    folder_queue.append(child_url)
                    continue

                if not drive_item_in_time_window(item, start, end):
                    continue

                # Non-file items (e.g. OneNote notebooks without a "file" facet) are
                # yielded too. The downstream conversion filters by extension and mime.
                yield DriveItemData.from_graph_json(item)

            page_url = data.get("@odata.nextLink")


def iter_drive_items_delta(
    client: GraphApiClient,
    drive_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    page_size: int = 200,
) -> Generator[DriveItemData, None, None]:
    """Yield DriveItemData for every file in a drive via the Graph delta API.

    Uses the flat delta endpoint instead of recursive folder traversal.
    On subsequent runs (start > epoch), passes the start timestamp as a
    delta token so that only changed items are returned.

    Falls back to full enumeration if the API returns 410 Gone (expired token).
    """
    use_timestamp_token = start is not None and start > _EPOCH

    initial_url = f"{client.graph_api_base}/drives/{drive_id}/root/delta"
    if use_timestamp_token:
        assert start is not None  # for type-checking
        token = quote(start.isoformat(timespec="seconds"))
        initial_url += f"?token={token}"

    yield from iter_delta_pages(
        client,
        initial_url=initial_url,
        drive_id=drive_id,
        start=start,
        end=end,
        page_size=page_size,
        allow_full_resync=use_timestamp_token,
    )


def iter_delta_pages(
    client: GraphApiClient,
    initial_url: str,
    drive_id: str,
    start: datetime | None,
    end: datetime | None,
    page_size: int,
    allow_full_resync: bool,
) -> Generator[DriveItemData, None, None]:
    """Paginate through delta API responses, yielding file DriveItemData.

    If the API responds with 410 Gone and allow_full_resync is True,
    restarts with a full delta enumeration.
    """
    page_url: str | None = initial_url
    params: dict[str, str] | None = {
        "$top": str(page_size),
        "$select": DRIVE_ITEM_SELECT_FIELDS,
    }

    while page_url:
        try:
            data = client.get_json(page_url, params)
        except requests.HTTPError as e:
            # 410 means the delta token expired, so we need to fall back to full enumeration
            if e.response is not None and e.response.status_code == 410:
                if not allow_full_resync:
                    raise
                logger.warning(
                    "Delta token expired (410 Gone) for drive '%s'. Falling back to full delta enumeration.",
                    drive_id,
                )
                yield from iter_delta_pages(
                    client,
                    initial_url=f"{client.graph_api_base}/drives/{drive_id}/root/delta",
                    drive_id=drive_id,
                    start=start,
                    end=end,
                    page_size=page_size,
                    allow_full_resync=False,
                )
                return
            raise

        params = None  # nextLink/deltaLink already embed query params

        for item in data.get("value", []):
            if (
                DRIVE_ITEM_FOLDER_PROPERTY in item
                or DRIVE_ITEM_DELETED_PROPERTY in item
            ):
                continue

            if not drive_item_in_time_window(item, start, end):
                continue

            yield DriveItemData.from_graph_json(item)

        page_url = data.get("@odata.nextLink")
        if not page_url:
            break


def build_delta_start_url(
    client: GraphApiClient,
    drive_id: str,
    start: datetime | None = None,
    page_size: int = 200,
) -> str:
    """Build the initial delta API URL with query parameters embedded.

    Embeds ``$top``, ``$select``, and optionally ``token`` so the URL can be
    stored in a checkpoint without a separate params dict.
    """
    base_url = f"{client.graph_api_base}/drives/{drive_id}/root/delta"
    params = [
        f"$top={page_size}",
        f"$select={DRIVE_ITEM_SELECT_FIELDS}",
    ]
    if start is not None and start > _EPOCH:
        token = quote(start.isoformat(timespec="seconds"))
        params.append(f"token={token}")
    return f"{base_url}?{'&'.join(params)}"


def fetch_one_delta_page(
    client: GraphApiClient,
    page_url: str,
    drive_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    page_size: int = 200,
) -> tuple[list[DriveItemData], str | None]:
    """Fetch a single page of delta API results.

    Returns ``(items, next_page_url)``.  *next_page_url* is ``None`` when
    the delta enumeration is complete (deltaLink with no nextLink).

    On 410 Gone (expired token) returns ``([], full_resync_url)`` so
    the caller can store the resync URL in the checkpoint and retry on
    the next cycle.
    """
    try:
        data = client.get_json(page_url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 410:
            logger.warning(
                "Delta token expired (410 Gone) for drive '%s'. Will restart with full delta enumeration.",
                drive_id,
            )
            full_url = (
                f"{client.graph_api_base}/drives/{drive_id}/root/delta?"
                f"$top={page_size}&$select={DRIVE_ITEM_SELECT_FIELDS}"
            )
            return [], full_url
        raise

    items: list[DriveItemData] = []
    for item in data.get("value", []):
        if DRIVE_ITEM_FOLDER_PROPERTY in item or DRIVE_ITEM_DELETED_PROPERTY in item:
            continue
        if not drive_item_in_time_window(item, start, end):
            continue
        items.append(DriveItemData.from_graph_json(item))

    next_url = data.get("@odata.nextLink")
    if next_url:
        return items, next_url
    return items, None
