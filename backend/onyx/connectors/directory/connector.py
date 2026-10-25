"""Checkpointed connector for local or mounted read-only directories.

Based on the DirectoryConnector proof of concept from Onyx PR #6711. Source
discovery stays separate from parsing: walks are cheap and resumable, while
files use Onyx's existing native file-processing path one at a time.
"""

import hashlib
import os
import re
import unicodedata
from collections.abc import Generator, Iterator
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

from pydantic import BaseModel
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.file.connector import _process_file
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ALLOWED_ROOTS_ENV = "DIRECTORY_CONNECTOR_ALLOWED_ROOTS"
_DEFAULT_MAX_FILE_SIZE_MB = 512
_DEFAULT_MAX_DIRECTORIES_PER_BATCH = 1000
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CurrentDirectory(BaseModel):
    """Resumable state for one directory, relative to the configured root."""

    relative_directory: str
    file_names: list[str]
    offset: int = 0


class DirectoryCheckpoint(ConnectorCheckpoint):
    pending_directories: list[str] | None = None
    current_directory: CurrentDirectory | None = None


class DirectoryConnector(
    CheckpointedConnector[DirectoryCheckpoint], SlimConnector, Resolver
):
    """Index mounted files with stable per-source identities and safe pruning."""

    def __init__(
        self,
        root_directory: str,
        source_id: str | None = None,
        recursive: bool = True,
        file_extensions: list[str] | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        exclude_hidden: bool = True,
        batch_size: int = INDEX_BATCH_SIZE,
        max_file_size_mb: int = _DEFAULT_MAX_FILE_SIZE_MB,
        poll_overlap_seconds: int = 5,
        minimum_prune_files: int = 1,
        max_directories_per_batch: int = _DEFAULT_MAX_DIRECTORIES_PER_BATCH,
        link_base_url: str | None = None,
    ) -> None:
        self.root_directory = os.path.realpath(os.path.abspath(root_directory))
        # The UI form does not set a source_id, so configs created (or edited)
        # there omit it. A stable identity is derived from the resolved root
        # instead: the same root always yields the same document ids.
        self.source_id = (
            source_id.strip().lower()
            if source_id and source_id.strip()
            else self._derive_source_id(self.root_directory)
        )
        self.recursive = bool(recursive)
        self.exclude_hidden = bool(exclude_hidden)
        self.batch_size = int(batch_size)
        # 0 = unlimited: no per-file size check is performed.
        self.max_file_size_mb = int(max_file_size_mb)
        self.max_file_size_bytes = self.max_file_size_mb * 1024 * 1024
        self.poll_overlap_seconds = int(poll_overlap_seconds)
        self.minimum_prune_files = int(minimum_prune_files)
        self.max_directories_per_batch = int(max_directories_per_batch)
        self.link_base_url = link_base_url.rstrip("/") if link_base_url else None

        configured_extensions = (
            file_extensions
            if file_extensions is not None
            else sorted(OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS)
        )
        self.file_extensions = {
            self._normalize_extension(extension) for extension in configured_extensions
        }
        try:
            self.include_patterns = [
                re.compile(pattern) for pattern in (include_patterns or [])
            ]
            self.exclude_patterns = [
                re.compile(pattern) for pattern in (exclude_patterns or [])
            ]
        except re.error as error:
            raise ConnectorValidationError(
                f"Invalid directory path pattern: {error}"
            ) from error
        self._validate_configuration_values()

    @staticmethod
    def _derive_source_id(root_directory: str) -> str:
        digest = hashlib.sha256(root_directory.encode("utf-8")).hexdigest()
        return f"dir-{digest[:16]}"

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        normalized = str(extension).strip().lower()
        if not normalized:
            raise ConnectorValidationError("File extensions must not be empty.")
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        if "/" in normalized or "\\" in normalized:
            raise ConnectorValidationError(f"Invalid file extension '{extension}'.")
        return normalized

    def _validate_configuration_values(self) -> None:
        if not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ConnectorValidationError(
                "source_id must start with a lower-case letter or digit and contain "
                "only lower-case letters, digits, '.', '_' or '-' (max 64 characters)."
            )
        if not self.file_extensions:
            raise ConnectorValidationError(
                "At least one file extension must be configured."
            )
        unsupported = self.file_extensions - OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
        if unsupported:
            raise ConnectorValidationError(
                "Unsupported file extensions: " + ", ".join(sorted(unsupported))
            )
        if not 1 <= self.batch_size <= 100:
            raise ConnectorValidationError("batch_size must be between 1 and 100.")
        if self.max_file_size_mb < 0:
            raise ConnectorValidationError(
                "max_file_size_mb must be 0 (unlimited) or greater."
            )
        if not 0 <= self.poll_overlap_seconds <= 3600:
            raise ConnectorValidationError(
                "poll_overlap_seconds must be between 0 and 3600."
            )
        if self.minimum_prune_files < 0:
            raise ConnectorValidationError(
                "minimum_prune_files must be zero or greater."
            )
        if self.max_directories_per_batch < 0:
            raise ConnectorValidationError(
                "max_directories_per_batch must be 0 (unlimited) or greater."
            )
        if self.max_directories_per_batch > 100_000:
            raise ConnectorValidationError(
                "max_directories_per_batch must be between 1 and 100000 "
                "(0 = unlimited)."
            )

    @override
    def load_credentials(  # noqa: ARG002
        self, credentials: dict[str, Any]
    ) -> dict[str, Any] | None:
        return None

    @staticmethod
    def _configured_allowed_roots() -> list[str]:
        raw_roots = os.environ.get(_ALLOWED_ROOTS_ENV, "")
        return [
            os.path.realpath(os.path.abspath(root.strip()))
            for root in raw_roots.split(os.pathsep)
            if root.strip()
        ]

    def _validate_allowed_root(self) -> None:
        allowed_roots = self._configured_allowed_roots()
        if not allowed_roots:
            raise ConnectorValidationError(
                f"{_ALLOWED_ROOTS_ENV} must contain at least one approved root."
            )
        for allowed_root in allowed_roots:
            try:
                if (
                    os.path.commonpath([self.root_directory, allowed_root])
                    == allowed_root
                ):
                    return
            except ValueError:
                continue
        raise ConnectorValidationError(
            "The configured directory is outside DIRECTORY_CONNECTOR_ALLOWED_ROOTS."
        )

    def _validate_root_available(self) -> None:
        self._validate_allowed_root()
        if not os.path.isdir(self.root_directory):
            raise ConnectorValidationError(
                f"Directory source is unavailable: {self.root_directory}"
            )
        try:
            with os.scandir(self.root_directory) as entries:
                next(entries, None)
        except OSError as error:
            raise ConnectorValidationError(
                f"Directory source cannot be read: {self.root_directory}"
            ) from error

    @override
    def validate_connector_settings(self) -> None:
        self._validate_root_available()

    @override
    def build_dummy_checkpoint(self) -> DirectoryCheckpoint:
        return DirectoryCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> DirectoryCheckpoint:
        return DirectoryCheckpoint.model_validate_json(checkpoint_json)

    @staticmethod
    def _validate_relative_path(relative_path: str) -> None:
        """Rejects paths that would escape the root. Does not transform the
        name: the raw form is what the filesystem stores (see _absolute_path)."""
        posix_path = PurePosixPath(relative_path.replace("\\", "/"))
        normalized = unicodedata.normalize("NFC", posix_path.as_posix())
        if (
            normalized.startswith("../")
            or normalized == ".."
            or posix_path.is_absolute()
        ):
            raise ConnectorValidationError(
                "Directory path escaped the configured root."
            )

    @staticmethod
    def _normalize_relative_path(relative_path: str) -> str:
        posix_path = PurePosixPath(relative_path.replace("\\", "/"))
        normalized = unicodedata.normalize("NFC", posix_path.as_posix())
        if normalized in {"", "."}:
            return ""
        DirectoryConnector._validate_relative_path(relative_path)
        return normalized

    def _absolute_path(self, relative_path: str) -> str:
        # Resolve the raw relative path against the root. Normalizing first
        # (backslash to slash, Unicode NFC) would silently miss names the
        # filesystem stores in a different form.
        self._validate_relative_path(relative_path)
        candidate = os.path.realpath(os.path.join(self.root_directory, relative_path))
        if os.path.commonpath([candidate, self.root_directory]) != self.root_directory:
            raise ConnectorValidationError(
                "Directory path escaped the configured root."
            )
        return candidate

    def _document_id(self, relative_path: str) -> str:
        normalized = self._normalize_relative_path(relative_path)
        digest = hashlib.sha256(
            f"{self.source_id}\0{normalized}".encode("utf-8")
        ).hexdigest()
        return f"directory:{self.source_id}:{digest}"

    def _directory_uri(self, relative_path: str) -> str:
        # The raw path rides in the URI so reindex resolves the name the
        # filesystem actually stores (see _absolute_path).
        self._validate_relative_path(relative_path)
        return f"directory://{self.source_id}/{quote(relative_path, safe='/')}"

    def _source_link(self, relative_path: str) -> str | None:
        if self.link_base_url is None:
            return None
        normalized = self._normalize_relative_path(relative_path)
        return f"{self.link_base_url}/{quote(normalized, safe='/')}"

    def _relative_path_from_failure(self, failure: ConnectorFailure) -> str | None:
        if failure.failed_document is None or not failure.failed_document.document_link:
            return None
        parsed = urlparse(failure.failed_document.document_link)
        if parsed.scheme != "directory" or parsed.netloc != self.source_id:
            return None
        relative_path = unquote(parsed.path.lstrip("/"))
        self._validate_relative_path(relative_path)
        return relative_path

    def _is_hidden_path(self, relative_path: str) -> bool:
        return any(part.startswith(".") for part in PurePosixPath(relative_path).parts)

    def _is_candidate_file(self, relative_path: str) -> bool:
        normalized = self._normalize_relative_path(relative_path)
        if self.exclude_hidden and self._is_hidden_path(normalized):
            return False
        if PurePosixPath(normalized).suffix.lower() not in self.file_extensions:
            return False
        if self.include_patterns and not any(
            pattern.search(normalized) for pattern in self.include_patterns
        ):
            return False
        return not any(pattern.search(normalized) for pattern in self.exclude_patterns)

    def _scan_directory(self, relative_directory: str) -> tuple[list[str], list[str]]:
        absolute_directory = self._absolute_path(relative_directory)
        file_names: list[str] = []
        subdirectories: list[str] = []
        with os.scandir(absolute_directory) as entries:
            for entry in entries:
                relative_path = str(PurePosixPath(relative_directory) / entry.name)
                if entry.is_file(follow_symlinks=False):
                    if self._is_candidate_file(relative_path):
                        file_names.append(entry.name)
                elif self.recursive and entry.is_dir(follow_symlinks=False):
                    if not (self.exclude_hidden and entry.name.startswith(".")):
                        subdirectories.append(relative_path)
        file_names.sort()
        subdirectories.sort(reverse=True)
        return file_names, subdirectories

    def _failure_for_file(
        self,
        relative_path: str,
        message: str,
        exception: Exception | None = None,
    ) -> ConnectorFailure:
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=self._document_id(relative_path),
                document_link=self._directory_uri(relative_path),
            ),
            failure_message=message,
            exception=exception,
        )

    def _process_path(
        self,
        relative_path: str,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        apply_time_window: bool,
    ) -> Document | ConnectorFailure | None:
        normalized = self._normalize_relative_path(relative_path)
        absolute_path = self._absolute_path(relative_path)
        document_id = self._document_id(normalized)
        source_link = self._source_link(normalized)

        def no_follow_opener(path: str, flags: int) -> int:
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))

        try:
            with open(absolute_path, "rb", opener=no_follow_opener) as file_handle:
                stat_before = os.fstat(file_handle.fileno())

                if apply_time_window:
                    effective_start = max(
                        0.0, float(start or 0) - self.poll_overlap_seconds
                    )
                    effective_end = float(end) if end is not None else float("inf")
                    change_timestamp = max(stat_before.st_mtime, stat_before.st_ctime)
                    if not effective_start <= change_timestamp <= effective_end:
                        return None

                if stat_before.st_size <= 0:
                    return self._failure_for_file(
                        normalized, "Directory file is empty."
                    )
                if (
                    self.max_file_size_bytes
                    and stat_before.st_size > self.max_file_size_bytes
                ):
                    return self._failure_for_file(
                        normalized,
                        "Directory file exceeds configured max_file_size_mb "
                        f"({stat_before.st_size} bytes > "
                        f"{self.max_file_size_bytes} bytes).",
                    )

                file_name = os.path.basename(absolute_path)
                metadata: dict[str, Any] = {
                    "id": document_id,
                    "connector_type": DocumentSource.DIRECTORY.value,
                    "file_display_name": file_name,
                    "title": file_name,
                    "doc_updated_at": datetime.fromtimestamp(
                        stat_before.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "link": source_link,
                    "directory_source": self.source_id,
                    "relative_path": normalized,
                    "file_size_bytes": str(stat_before.st_size),
                    "file_extension": PurePosixPath(normalized).suffix.lower(),
                }
                documents = _process_file(
                    file_id=document_id,
                    file_name=file_name,
                    file=file_handle,
                    metadata=metadata,
                    pdf_pass=None,
                    file_type=None,
                    stage=self.raw_file_callback,
                )
                stat_handle_after = os.fstat(file_handle.fileno())
            stat_path_after = os.stat(absolute_path, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as error:
            return self._failure_for_file(
                normalized, f"Failed to read directory file: {error}", error
            )
        except Exception as error:
            logger.exception("Failed to process directory file %s", normalized)
            return self._failure_for_file(
                normalized, f"Failed to process directory file: {error}", error
            )

        if (
            stat_handle_after.st_dev != stat_before.st_dev
            or stat_handle_after.st_ino != stat_before.st_ino
            or stat_handle_after.st_size != stat_before.st_size
            or stat_handle_after.st_mtime_ns != stat_before.st_mtime_ns
            or stat_handle_after.st_ctime_ns != stat_before.st_ctime_ns
            or stat_path_after.st_dev != stat_before.st_dev
            or stat_path_after.st_ino != stat_before.st_ino
            or stat_path_after.st_size != stat_before.st_size
            or stat_path_after.st_mtime_ns != stat_before.st_mtime_ns
            or stat_path_after.st_ctime_ns != stat_before.st_ctime_ns
        ):
            return self._failure_for_file(
                normalized,
                "Directory file changed while it was being processed; it will be retried.",
            )
        if not documents or not any(document.sections for document in documents):
            return self._failure_for_file(
                normalized, "Onyx extracted no indexable content from the file."
            )

        document = documents[0]
        document.id = document_id
        document.source = DocumentSource.DIRECTORY
        document.title = file_name
        document.semantic_identifier = normalized
        document.doc_updated_at = datetime.fromtimestamp(
            stat_before.st_mtime, tz=timezone.utc
        )
        document.metadata.pop("id", None)
        document.metadata.update(
            {
                "directory_source": self.source_id,
                "relative_path": normalized,
                "file_size_bytes": str(stat_before.st_size),
                "file_extension": PurePosixPath(normalized).suffix.lower(),
            }
        )
        return document

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: DirectoryCheckpoint,
    ) -> CheckpointOutput[DirectoryCheckpoint]:
        self._validate_root_available()
        checkpoint = checkpoint.model_copy(deep=True)
        if checkpoint.pending_directories is None:
            checkpoint.pending_directories = [""]

        processed_files = 0
        scanned_directories = 0
        while processed_files < self.batch_size:
            current = checkpoint.current_directory
            if current is not None:
                while (
                    current.offset < len(current.file_names)
                    and processed_files < self.batch_size
                ):
                    file_name = current.file_names[current.offset]
                    current.offset += 1
                    processed_files += 1
                    relative_path = str(
                        PurePosixPath(current.relative_directory) / file_name
                    )
                    result = self._process_path(
                        relative_path, start=start, end=end, apply_time_window=True
                    )
                    if result is not None:
                        yield result
                if current.offset >= len(current.file_names):
                    checkpoint.current_directory = None
                if processed_files >= self.batch_size:
                    break
                continue

            if not checkpoint.pending_directories:
                checkpoint.has_more = False
                return checkpoint
            if (
                self.max_directories_per_batch
                and scanned_directories >= self.max_directories_per_batch
            ):
                break

            relative_directory = checkpoint.pending_directories.pop()
            scanned_directories += 1
            try:
                file_names, subdirectories = self._scan_directory(relative_directory)
            except OSError as error:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=self._directory_uri(relative_directory)
                    ),
                    failure_message=f"Failed to scan directory: {error}",
                    exception=error,
                )
                continue
            checkpoint.pending_directories.extend(subdirectories)
            if file_names:
                checkpoint.current_directory = CurrentDirectory(
                    relative_directory=relative_directory,
                    file_names=file_names,
                )

        checkpoint.has_more = bool(
            checkpoint.current_directory or checkpoint.pending_directories
        )
        return checkpoint

    def _iter_candidate_relative_paths(self) -> Iterator[str]:
        self._validate_root_available()
        pending_directories = [""]
        while pending_directories:
            relative_directory = pending_directories.pop()
            file_names, subdirectories = self._scan_directory(relative_directory)
            pending_directories.extend(subdirectories)
            for file_name in file_names:
                yield str(PurePosixPath(relative_directory) / file_name)

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        del start, end
        candidate_paths: list[str] = []
        for relative_path in self._iter_candidate_relative_paths():
            if callback and callback.should_stop():
                return
            candidate_paths.append(relative_path)
            if callback and len(candidate_paths) % 1000 == 0:
                callback.progress("directory_slim_preflight", 1000)
        if len(candidate_paths) < self.minimum_prune_files:
            raise ConnectorValidationError(
                "Directory prune preflight found fewer files than the configured "
                f"minimum ({len(candidate_paths)} < {self.minimum_prune_files})."
            )

        batch: list[SlimDocument | HierarchyNode] = []
        for relative_path in candidate_paths:
            if callback and callback.should_stop():
                return
            batch.append(SlimDocument(id=self._document_id(relative_path)))
            if len(batch) >= self.batch_size:
                yield batch
                if callback:
                    callback.progress("directory_slim", len(batch))
                batch = []
        if batch:
            yield batch
            if callback:
                callback.progress("directory_slim", len(batch))

    @override
    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        del include_permissions
        self._validate_root_available()

        relative_paths = [self._relative_path_from_failure(error) for error in errors]
        unresolved_document_ids = {
            error.failed_document.document_id
            for error, relative_path in zip(errors, relative_paths, strict=True)
            if relative_path is None and error.failed_document is not None
        }
        paths_by_document_id: dict[str, str] = {}
        if unresolved_document_ids:
            for candidate_path in self._iter_candidate_relative_paths():
                document_id = self._document_id(candidate_path)
                if document_id in unresolved_document_ids:
                    paths_by_document_id[document_id] = candidate_path
                    if len(paths_by_document_id) == len(unresolved_document_ids):
                        break

        for failure, relative_path in zip(errors, relative_paths, strict=True):
            if relative_path is None and failure.failed_document is not None:
                relative_path = paths_by_document_id.get(
                    failure.failed_document.document_id
                )
            if relative_path is None:
                yield failure
                continue
            result = self._process_path(
                relative_path, start=None, end=None, apply_time_window=False
            )
            if result is not None:
                yield result
