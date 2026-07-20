import posixpath
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.cross_connector_utils.tabular_section_utils import is_tabular_file
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    tabular_file_to_sections,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import detect_encoding
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.image_utils import make_image_callback
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

SEAFILE_API_TOKEN_KEY = "seafile_api_token"
SEAFILE_DEFAULT_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
SEAFILE_ADDITIONAL_TEXT_EXTENSIONS = frozenset({".markdown"})
SEAFILE_SUPPORTED_EXTENSIONS = frozenset(
    OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS | SEAFILE_ADDITIONAL_TEXT_EXTENSIONS
)
SEAFILE_SKIP_EXAMPLE_LIMIT = 3
SEAFILE_MODIFIED_TIME_FIELDS = (
    "mtime",
    "modified",
    "last_modified",
    "last_modified_time",
    "lastModified",
    "lastModifiedTime",
    "lastModifiedDateTime",
    "updated_at",
    "updatedAt",
)


class SeafileDirCursor(BaseModel):
    repo_id: str
    path: str
    last_child_path: str | None = None


class SeafileCheckpoint(ConnectorCheckpoint):
    initialized: bool = False
    pending_dirs: list[SeafileDirCursor] = Field(default_factory=list)
    current_dir: SeafileDirCursor | None = None
    emitted_hierarchy_node_raw_ids: set[str] = Field(default_factory=set)


@dataclass
class _SeafileSkipSummary:
    skipped_by_reason: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    examples_by_reason: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def record(self, reason: str, repo_id: str, path: str) -> None:
        self.skipped_by_reason[reason] += 1
        examples = self.examples_by_reason[reason]
        if len(examples) < SEAFILE_SKIP_EXAMPLE_LIMIT:
            examples.append(f"{repo_id}:{path}")

    def log(self) -> None:
        if not self.skipped_by_reason:
            return

        logger.info(
            "Skipped Seafile files: %s",
            ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(self.skipped_by_reason.items())
            ),
        )
        logger.debug("Skipped Seafile file examples: %s", dict(self.examples_by_reason))


def normalize_seafile_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ConnectorValidationError("Seafile base URL is required")
    if not normalized.startswith(("http://", "https://")):
        raise ConnectorValidationError(
            "Seafile base URL must start with http:// or https://"
        )
    return normalized


def _normalize_path(path: str | None) -> str:
    if not path or path == "/":
        return "/"

    normalized = posixpath.normpath("/" + path.strip().lstrip("/"))
    return "/" if normalized == "/." else normalized


def _join_path(parent: str, name: str) -> str:
    return _normalize_path(str(PurePosixPath(parent) / name))


def _file_extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def _document_id(repo_id: str, path: str) -> str:
    return f"seafile:{repo_id}:{_normalize_path(path)}"


def _library_hierarchy_raw_id(repo_id: str) -> str:
    return f"seafile:library:{repo_id}"


def _folder_hierarchy_raw_id(repo_id: str, path: str) -> str:
    return f"seafile:folder:{repo_id}:{_normalize_path(path)}"


def _parent_hierarchy_raw_id(repo_id: str, path: str) -> str:
    folder_path = _folder_path(path)
    if folder_path == "/":
        return _library_hierarchy_raw_id(repo_id)
    return _folder_hierarchy_raw_id(repo_id, folder_path)


def _folder_path(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return _normalize_path(parent)


def _path_parts(path: str) -> list[str]:
    return [part for part in PurePosixPath(path).parts if part != "/"]


def _folder_path_parts(path: str) -> list[str]:
    return _path_parts(_folder_path(path))


def _raw_modified_time(item: dict[str, Any]) -> Any | None:
    for field_name in SEAFILE_MODIFIED_TIME_FIELDS:
        raw_value = item.get(field_name)
        if raw_value is not None and raw_value != "":
            return raw_value
    return None


def _parse_modified_time(raw_value: Any) -> datetime | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None

    if isinstance(raw_value, (int, float)):
        try:
            return datetime.fromtimestamp(raw_value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            logger.warning("Unable to parse Seafile modified time: %s", raw_value)
            return None

    if isinstance(raw_value, str):
        stripped_value = raw_value.strip()
        if not stripped_value:
            return None

        try:
            numeric_value = float(stripped_value)
        except ValueError:
            pass
        else:
            try:
                return datetime.fromtimestamp(numeric_value, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                logger.warning("Unable to parse Seafile modified time: %s", raw_value)
                return None

        try:
            return time_str_to_utc(stripped_value)
        except ValueError:
            logger.warning("Unable to parse Seafile modified time: %s", raw_value)

    return None


def _modified_time(item: dict[str, Any]) -> datetime | None:
    return _parse_modified_time(_raw_modified_time(item))


def _is_dir(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type", "")).lower()
    return item_type in {"dir", "directory", "folder"}


def _is_file(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type", "")).lower()
    return item_type in {"file", "blob"} or ("size" in item and not _is_dir(item))


class SeafileConnector(CheckpointedConnector[SeafileCheckpoint], SlimConnector):
    def __init__(
        self,
        base_url: str,
        repo_ids: list[str],
        path_prefixes: list[str] | None = None,
        allowed_extensions: list[str] | None = None,
        max_file_size_bytes: int = SEAFILE_DEFAULT_MAX_FILE_SIZE_BYTES,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url = normalize_seafile_base_url(base_url)
        self.repo_ids = [repo_id.strip() for repo_id in repo_ids if repo_id.strip()]
        self.path_prefixes = [
            _normalize_path(path_prefix) for path_prefix in (path_prefixes or ["/"])
        ]
        configured_extensions = allowed_extensions or list(SEAFILE_SUPPORTED_EXTENSIONS)
        self.allowed_extensions = {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in configured_extensions
            if extension.strip()
        }
        self.max_file_size_bytes = max_file_size_bytes
        self.batch_size = batch_size
        self.api_token: str | None = None
        self._library_names_by_repo_id: dict[str, str | None] = {}

        if not self.repo_ids:
            raise ConnectorValidationError(
                "At least one Seafile repo/library ID is required"
            )
        if not self.allowed_extensions:
            raise ConnectorValidationError(
                "At least one Seafile file extension is required"
            )
        unsupported_extensions = self.allowed_extensions - SEAFILE_SUPPORTED_EXTENSIONS
        if unsupported_extensions:
            raise ConnectorValidationError(
                "Unsupported Seafile extensions: "
                + ", ".join(sorted(unsupported_extensions))
            )
        if self.max_file_size_bytes <= 0:
            raise ConnectorValidationError(
                "Seafile max file size must be greater than zero"
            )

    def _configured_repo_ids(self) -> list[str]:
        seen_repo_ids: set[str] = set()
        repo_ids: list[str] = []
        for repo_id in self.repo_ids:
            if repo_id in seen_repo_ids:
                continue
            seen_repo_ids.add(repo_id)
            repo_ids.append(repo_id)
        return repo_ids

    def _configured_path_prefixes(self) -> list[str]:
        configured_path_prefixes: list[str] = []
        for path_prefix in sorted(set(self.path_prefixes), key=lambda path: (path,)):
            if any(
                path_prefix == existing_prefix
                or path_prefix.startswith(existing_prefix.rstrip("/") + "/")
                for existing_prefix in configured_path_prefixes
            ):
                continue
            configured_path_prefixes.append(path_prefix)
        return configured_path_prefixes

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = str(credentials.get(SEAFILE_API_TOKEN_KEY, "")).strip()
        if not api_token:
            raise ConnectorMissingCredentialError("Seafile")
        self.api_token = api_token
        return None

    @property
    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            raise ConnectorMissingCredentialError("Seafile")
        return {"Authorization": f"Token {self.api_token}"}

    def _handle_request_error(
        self,
        exc: requests.HTTPError | requests.RequestException,
        *,
        context: str,
    ) -> None:
        response = getattr(exc, "response", None)
        status_code = response.status_code if response is not None else None
        raw_detail = response.text if response is not None else str(exc)
        detail = raw_detail[:500]

        if status_code == 401:
            raise CredentialExpiredError(
                f"Seafile API token is invalid or expired (HTTP 401): {context}."
            ) from exc
        if status_code == 403:
            raise InsufficientPermissionsError(
                "Seafile API token does not have access to the requested library/path. "
                "Use a dedicated Seafile service account with read access to the "
                f"configured library and path (HTTP 403): {context}."
            ) from exc
        if status_code == 404:
            raise ConnectorValidationError(
                f"Seafile repo/library or path was not found (HTTP 404): {context}."
            ) from exc
        if status_code == 429:
            raise ConnectorValidationError(
                f"Seafile API rate limit exceeded (HTTP 429): {context}. {detail}"
            ) from exc
        if status_code is not None and status_code >= 500:
            raise ConnectorValidationError(
                f"Seafile API server error (HTTP {status_code}): {context}. {detail}"
            ) from exc

        raise ConnectorValidationError(
            f"Seafile API request failed: {context}. {detail}"
        ) from exc

    def _request_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        context: str,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = request_with_retries(
                method="GET",
                url=url,
                headers=self._headers,
                params=params,
            )
        except (requests.HTTPError, requests.RequestException) as exc:
            self._handle_request_error(exc, context=context)
            raise

        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorValidationError(
                f"Seafile API returned malformed JSON: {context}."
            ) from exc

    def _request_bytes(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        context: str,
    ) -> bytes:
        try:
            response = request_with_retries(
                method="GET",
                url=url,
                headers=headers,
            )
        except (requests.HTTPError, requests.RequestException) as exc:
            self._handle_request_error(exc, context=context)
            raise

        return response.content

    def _list_dir(self, repo_id: str, path: str) -> list[dict[str, Any]]:
        data = self._request_json(
            f"/api2/repos/{quote(repo_id, safe='')}/dir/",
            params={"p": path},
            context=f"list directory repo={repo_id} path={path}",
        )
        if not isinstance(data, list):
            raise ConnectorValidationError(
                f"Unexpected Seafile directory response: repo={repo_id} path={path}"
            )
        return [item for item in data if isinstance(item, dict)]

    def _get_download_link(self, repo_id: str, path: str) -> str:
        data = self._request_json(
            f"/api2/repos/{quote(repo_id, safe='')}/file/",
            params={"p": path, "reuse": "1"},
            context=f"get file download link repo={repo_id} path={path}",
        )
        if isinstance(data, str):
            return data
        if isinstance(data, dict) and isinstance(data.get("download_link"), str):
            return data["download_link"]
        raise ConnectorValidationError(
            f"Unexpected Seafile file download response: repo={repo_id} path={path}"
        )

    def _get_library_name(self, repo_id: str) -> str | None:
        if repo_id in self._library_names_by_repo_id:
            return self._library_names_by_repo_id[repo_id]

        try:
            data = self._request_json(
                f"/api2/repos/{quote(repo_id, safe='')}/",
                context=f"get library metadata repo={repo_id}",
            )
        except ConnectorValidationError as exc:
            logger.debug("Unable to fetch Seafile library metadata: %s", exc)
            self._library_names_by_repo_id[repo_id] = None
            return None

        library_name: str | None = None
        if isinstance(data, dict):
            for field_name in ("name", "repo_name", "repoName"):
                value = data.get(field_name)
                if isinstance(value, str) and value.strip():
                    library_name = value.strip()
                    break

        self._library_names_by_repo_id[repo_id] = library_name
        return library_name

    def _walk_files(self) -> Iterator[tuple[str, str, dict[str, Any]]]:
        for repo_id in self._configured_repo_ids():
            for path_prefix in self._configured_path_prefixes():
                for path, item in self._walk_path(repo_id=repo_id, path=path_prefix):
                    if _is_file(item):
                        yield repo_id, path, item

    def _walk_path(
        self, repo_id: str, path: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        for item in self._list_dir(repo_id, path):
            name = str(item.get("name") or "")
            if not name:
                continue

            item_path = _normalize_path(str(item.get("path") or _join_path(path, name)))
            if _is_dir(item):
                yield item_path, item
                yield from self._walk_path(repo_id=repo_id, path=item_path)
            elif _is_file(item):
                yield item_path, item

    def _source_url(self, repo_id: str, path: str) -> str:
        encoded_path = quote(path, safe="/")
        return f"{self.base_url}/lib/{quote(repo_id, safe='')}/file{encoded_path}"

    def _library_hierarchy_node(self, repo_id: str) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=_library_hierarchy_raw_id(repo_id),
            raw_parent_id=None,
            display_name=self._get_library_name(repo_id) or repo_id,
            link=self._source_url(repo_id, "/"),
            node_type=HierarchyNodeType.FOLDER,
        )

    def _folder_hierarchy_node(self, repo_id: str, path: str) -> HierarchyNode:
        folder_path = _normalize_path(path)
        parent_path = _folder_path(folder_path)
        return HierarchyNode(
            raw_node_id=_folder_hierarchy_raw_id(repo_id, folder_path),
            raw_parent_id=(
                _library_hierarchy_raw_id(repo_id)
                if parent_path == "/"
                else _folder_hierarchy_raw_id(repo_id, parent_path)
            ),
            display_name=PurePosixPath(folder_path).name,
            link=self._source_url(repo_id, folder_path),
            node_type=HierarchyNodeType.FOLDER,
        )

    def _hierarchy_nodes_for_folder_path(
        self, repo_id: str, path: str
    ) -> Iterator[HierarchyNode]:
        for index, _part in enumerate(_path_parts(path)):
            folder_path = _normalize_path(
                "/" + "/".join(_path_parts(path)[: index + 1])
            )
            yield self._folder_hierarchy_node(repo_id, folder_path)

    def _emit_hierarchy_node_once(
        self,
        checkpoint: SeafileCheckpoint,
        node: HierarchyNode,
    ) -> HierarchyNode | None:
        if node.raw_node_id in checkpoint.emitted_hierarchy_node_raw_ids:
            return None

        checkpoint.emitted_hierarchy_node_raw_ids.add(node.raw_node_id)
        return node

    def _seed_checkpoint(self, checkpoint: SeafileCheckpoint) -> list[HierarchyNode]:
        nodes: list[HierarchyNode] = []
        pending_dirs: list[SeafileDirCursor] = []

        for repo_id in self._configured_repo_ids():
            library_node = self._emit_hierarchy_node_once(
                checkpoint, self._library_hierarchy_node(repo_id)
            )
            if library_node is not None:
                nodes.append(library_node)

            for path_prefix in self._configured_path_prefixes():
                for folder_node in self._hierarchy_nodes_for_folder_path(
                    repo_id, path_prefix
                ):
                    node = self._emit_hierarchy_node_once(checkpoint, folder_node)
                    if node is not None:
                        nodes.append(node)

                pending_dirs.append(
                    SeafileDirCursor(
                        repo_id=repo_id,
                        path=path_prefix,
                    )
                )

        checkpoint.initialized = True
        checkpoint.pending_dirs = pending_dirs
        checkpoint.has_more = bool(checkpoint.current_dir or checkpoint.pending_dirs)
        return nodes

    def _sorted_dir_children(
        self,
        repo_id: str,
        path: str,
        last_child_path: str | None,
    ) -> list[tuple[str, dict[str, Any]]]:
        children: list[tuple[str, dict[str, Any]]] = []
        for item in self._list_dir(repo_id, path):
            name = str(item.get("name") or "")
            if not name:
                continue
            item_path = _normalize_path(str(item.get("path") or _join_path(path, name)))
            children.append((item_path, item))

        children.sort(key=lambda child: (not _is_dir(child[1]), child[0]))
        if last_child_path is None:
            return children
        return [child for child in children if child[0] > last_child_path]

    def _should_index_file(
        self,
        repo_id: str,
        path: str,
        item: dict[str, Any],
        skip_summary: _SeafileSkipSummary | None = None,
    ) -> bool:
        extension = _file_extension(path)
        if extension not in self.allowed_extensions:
            if skip_summary:
                skip_summary.record("unsupported_extension", repo_id, path)
            logger.debug(
                "Skipping unsupported Seafile file extension: repo=%s path=%s",
                repo_id,
                path,
            )
            return False

        size = item.get("size")
        if isinstance(size, int | float) and size > self.max_file_size_bytes:
            if skip_summary:
                skip_summary.record("oversized_listing", repo_id, path)
            logger.debug(
                "Skipping oversized Seafile file: repo=%s path=%s size=%s limit=%s",
                repo_id,
                path,
                size,
                self.max_file_size_bytes,
            )
            return False

        return True

    def _file_to_document(
        self,
        repo_id: str,
        path: str,
        item: dict[str, Any],
        skip_summary: _SeafileSkipSummary | None = None,
    ) -> Document | None:
        if not self._should_index_file(repo_id, path, item, skip_summary):
            return None

        download_link = self._get_download_link(repo_id, path)
        raw_content = self._request_bytes(
            download_link,
            context=f"download file repo={repo_id} path={path}",
        )
        if len(raw_content) > self.max_file_size_bytes:
            if skip_summary:
                skip_summary.record("oversized_download", repo_id, path)
            logger.debug(
                "Skipping oversized Seafile file after download: repo=%s path=%s size=%s limit=%s",
                repo_id,
                path,
                len(raw_content),
                self.max_file_size_bytes,
            )
            return None

        filename = PurePosixPath(path).name
        extension = _file_extension(path)
        source_url = self._source_url(repo_id, path)
        sections: list[TextSection | ImageSection | TabularSection] = []

        try:
            if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
                image_section, _ = store_image_and_create_section(
                    image_data=raw_content,
                    file_id=_document_id(repo_id, path),
                    display_name=filename,
                    link=source_url,
                    file_origin=FileOrigin.CONNECTOR,
                )
                sections.append(image_section)
            elif extension == ".html":
                text = parse_html_page_basic(BytesIO(raw_content)).strip()
                if text:
                    sections.append(TextSection(text=text, link=source_url))
            elif is_tabular_file(filename):
                sections.extend(
                    tabular_file_to_sections(
                        file=BytesIO(raw_content),
                        file_name=filename,
                        link=source_url,
                    )
                )
            elif extension in OnyxFileExtensions.DOCUMENT_EXTENSIONS:
                extraction_result = extract_text_and_images(
                    file=BytesIO(raw_content),
                    file_name=filename,
                    image_callback=make_image_callback(
                        sections,
                        _document_id(repo_id, path),
                        filename,
                        source_url,
                    ),
                )
                if extraction_result.text_content.strip():
                    sections.append(
                        TextSection(
                            text=extraction_result.text_content.strip(),
                            link=source_url,
                        )
                    )
            else:
                raw_content_io = BytesIO(raw_content)
                encoding = detect_encoding(raw_content_io)
                text = raw_content.decode(encoding, errors="replace").strip()
                if text:
                    sections.append(TextSection(text=text, link=source_url))
        except Exception:
            if skip_summary:
                skip_summary.record("parser_failure", repo_id, path)
            logger.exception(
                "Failed to parse Seafile file: repo=%s path=%s",
                repo_id,
                path,
            )
            return None

        if not sections:
            if skip_summary:
                skip_summary.record("empty_extracted_text", repo_id, path)
            logger.debug(
                "Skipping Seafile file with no extracted content: repo=%s path=%s",
                repo_id,
                path,
            )
            return None

        folder_path = _folder_path(path)
        folder_path_parts = _folder_path_parts(path)
        metadata: dict[str, str | list[str]] = {
            "repo_id": repo_id,
            "library_id": repo_id,
            "path": path,
            "path_parts": _path_parts(path),
            "folder_path": folder_path,
            "folder_path_parts": folder_path_parts,
            "folder_name": PurePosixPath(folder_path).name,
            "filename": filename,
            "extension": extension,
            "source_url": source_url,
        }
        if library_name := self._get_library_name(repo_id):
            metadata["library_name"] = library_name
        if (size := item.get("size")) is not None:
            metadata["size"] = str(size)
        doc_metadata: dict[str, Any] = dict(metadata)
        if isinstance(size, int):
            doc_metadata["size"] = size
        elif isinstance(size, float):
            doc_metadata["size"] = int(size) if size.is_integer() else size

        raw_modified_time = _raw_modified_time(item)
        doc_updated_at = _parse_modified_time(raw_modified_time)
        if doc_updated_at is not None:
            metadata["modified_time"] = doc_updated_at.isoformat()
            doc_metadata["modified_time"] = doc_updated_at.isoformat()
        elif raw_modified_time is not None:
            metadata["raw_modified_time"] = str(raw_modified_time)
            doc_metadata["raw_modified_time"] = raw_modified_time

        return Document(
            id=_document_id(repo_id, path),
            sections=sections,
            source=DocumentSource.SEAFILE,
            semantic_identifier=filename,
            title=filename,
            metadata=metadata,
            doc_metadata=doc_metadata,
            doc_updated_at=doc_updated_at,
            parent_hierarchy_raw_node_id=_parent_hierarchy_raw_id(repo_id, path),
        )

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: SeafileCheckpoint,
    ) -> CheckpointOutput[SeafileCheckpoint]:
        emitted_document_count = 0
        skip_summary = _SeafileSkipSummary()

        try:
            if not checkpoint.initialized:
                for node in self._seed_checkpoint(checkpoint):
                    yield node

            while checkpoint.current_dir is not None or checkpoint.pending_dirs:
                if checkpoint.current_dir is None:
                    checkpoint.current_dir = checkpoint.pending_dirs.pop(0)

                current_dir = checkpoint.current_dir
                remaining_children = self._sorted_dir_children(
                    current_dir.repo_id,
                    current_dir.path,
                    current_dir.last_child_path,
                )

                for path, item in remaining_children:
                    current_dir.last_child_path = path
                    if _is_dir(item):
                        node = self._emit_hierarchy_node_once(
                            checkpoint,
                            self._folder_hierarchy_node(current_dir.repo_id, path),
                        )
                        if node is not None:
                            yield node

                        checkpoint.pending_dirs.append(
                            SeafileDirCursor(
                                repo_id=current_dir.repo_id,
                                path=path,
                            )
                        )
                        continue

                    if not _is_file(item):
                        continue

                    document = self._file_to_document(
                        current_dir.repo_id, path, item, skip_summary
                    )
                    if document is None:
                        continue

                    emitted_document_count += 1
                    yield document
                    if emitted_document_count >= self.batch_size:
                        checkpoint.has_more = True
                        return checkpoint

                checkpoint.current_dir = None

            checkpoint.has_more = False
            return checkpoint
        finally:
            skip_summary.log()

    def build_dummy_checkpoint(self) -> SeafileCheckpoint:
        return SeafileCheckpoint(
            has_more=True,
            initialized=False,
            pending_dirs=[],
            current_dir=None,
            emitted_hierarchy_node_raw_ids=set(),
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> SeafileCheckpoint:
        return SeafileCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        batch: list[SlimDocument | HierarchyNode] = []
        seen_document_ids: set[str] = set()
        seen_hierarchy_node_ids: set[str] = set()
        skip_summary = _SeafileSkipSummary()

        def add_hierarchy_node(node: HierarchyNode) -> None:
            if node.raw_node_id in seen_hierarchy_node_ids:
                return
            seen_hierarchy_node_ids.add(node.raw_node_id)
            batch.append(node)

        try:
            for repo_id in self._configured_repo_ids():
                add_hierarchy_node(self._library_hierarchy_node(repo_id))
                for path_prefix in self._configured_path_prefixes():
                    for node in self._hierarchy_nodes_for_folder_path(
                        repo_id, path_prefix
                    ):
                        add_hierarchy_node(node)
                    for path, item in self._walk_path(
                        repo_id=repo_id, path=path_prefix
                    ):
                        if _is_dir(item):
                            add_hierarchy_node(
                                self._folder_hierarchy_node(repo_id, path)
                            )
                            continue

                        if not self._should_index_file(
                            repo_id, path, item, skip_summary
                        ):
                            continue

                        document_id = _document_id(repo_id, path)
                        if document_id in seen_document_ids:
                            continue

                        seen_document_ids.add(document_id)
                        batch.append(
                            SlimDocument(
                                id=document_id,
                                parent_hierarchy_raw_node_id=_parent_hierarchy_raw_id(
                                    repo_id, path
                                ),
                            )
                        )
                        if len(batch) >= self.batch_size:
                            yield batch
                            batch = []

                        if callback:
                            callback.progress("retrieve_all_slim_docs", 1)

            if batch:
                yield batch
        finally:
            skip_summary.log()

    def validate_connector_settings(self) -> None:
        if not self.api_token:
            raise ConnectorMissingCredentialError("Seafile")

        # Validate the token and configured libraries/paths using a cheap directory list.
        for repo_id in self.repo_ids:
            for path_prefix in self.path_prefixes:
                self._list_dir(repo_id, path_prefix)
