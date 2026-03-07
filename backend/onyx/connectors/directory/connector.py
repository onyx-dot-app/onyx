"""Directory connector for indexing files from a local filesystem directory."""

import os
import re
from datetime import datetime
from datetime import timezone
from typing import Any

from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".bash",
}


class CurrentDirectory(BaseModel):
    """State for currently processing directory."""

    path: str
    todo_file_paths: list[str]
    offset: int = 0


class DirectoryCheckpoint(ConnectorCheckpoint):
    """Checkpoint model for directory scanning."""

    has_more: bool = True
    todo_directories: list[str] | None = None
    current_directory: CurrentDirectory | None = None


class DirectoryConnector(CheckpointedConnector[DirectoryCheckpoint]):
    """Connector that indexes text files from a local filesystem directory."""

    def __init__(
        self,
        root_directory: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        """
        Initialize DirectoryConnector.

        Args:
            root_directory: Absolute path to directory to scan
            recursive: Whether to scan subdirectories recursively
            exclude_patterns: List of regex patterns to exclude files by name
            batch_size: Files to process per batch
        """
        if not os.path.isdir(root_directory):
            raise ValueError(f"Root directory does not exist: {root_directory}")

        self.root_directory = os.path.abspath(root_directory)
        self.recursive = recursive
        self.exclude_patterns = exclude_patterns or []
        self.batch_size = batch_size

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """No credentials needed for local filesystem access."""
        return None

    def validate_connector_settings(self) -> None:
        """Validate root_directory exists and is accessible."""
        if not os.path.isdir(self.root_directory):
            raise ValueError(f"Root directory not found: {self.root_directory}")

    def build_dummy_checkpoint(self) -> DirectoryCheckpoint:
        """Build initial checkpoint for scanning."""
        return DirectoryCheckpoint(has_more=True, current_directory=None)

    def validate_checkpoint_json(self, checkpoint_json: str) -> DirectoryCheckpoint:
        """Validate and parse checkpoint JSON."""
        return DirectoryCheckpoint.model_validate_json(json_data=checkpoint_json)

    def _should_exclude_file(self, file_name: str) -> bool:
        """
        Check if file should be excluded based on regex patterns.

        Args:
            file_name: Name of the file (not full path)

        Returns:
            True if file matches any exclude pattern
        """
        for pattern in self.exclude_patterns:
            if re.search(pattern, file_name):
                logger.debug(f"Excluding file {file_name} matching pattern {pattern}")
                return True
        return False

    def _process_file(self, file_path: str) -> Document | None:
        """
        Process a single file and create Document.

        Args:
            file_path: Absolute path to file

        Returns:
            Document object or None if processing failed
        """
        try:
            file_name = os.path.basename(file_path)
            relative_path = os.path.relpath(file_path, self.root_directory)

            # Check if file extension is supported
            _, ext = os.path.splitext(file_name)
            if ext.lower() not in SUPPORTED_EXTENSIONS:
                logger.debug(
                    f"Skipping unsupported file type: {file_path} (extension: {ext})"
                )
                return None

            # Try to extract text
            with open(file_path, "rb") as file:
                extraction_result = extract_text_and_images(
                    file=file,
                    file_name=file_name,
                    pdf_pass=None,
                    content_type=None,
                )

            text_content = extraction_result.text_content.strip()

            # If no text extracted, try reading as plain text file
            if not text_content:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text_content = f.read().strip()
                except Exception:
                    pass

            # Skip if still no text content
            if not text_content:
                logger.debug(f"No text content extracted from {file_path}, skipping")
                return None

            # Create document
            sections = [
                TextSection(
                    link=f"file://{file_path}",
                    text=text_content,
                )
            ]

            stat_info = os.stat(file_path)
            doc_id = f"DIRECTORY_CONNECTOR__{relative_path.replace(os.sep, '/')}"

            return Document(
                id=doc_id,
                sections=sections,
                source=DocumentSource.DIRECTORY,
                semantic_identifier=relative_path,
                title=file_name,
                doc_updated_at=datetime.fromtimestamp(
                    stat_info.st_mtime, tz=timezone.utc
                ),
                metadata={
                    "file_path": file_path,
                    "file_name": file_name,
                },
            )

        except Exception as e:
            logger.warning(f"Failed to process file {file_path}: {e}")
            return None

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: DirectoryCheckpoint,
    ):
        """Load documents from checkpoint."""
        # Initialize: start with root directory
        if checkpoint.todo_directories is None:
            checkpoint.todo_directories = [self.root_directory]
            return checkpoint

        # Process files from current directory if we have one
        if checkpoint.current_directory is not None:
            current_dir = checkpoint.current_directory
            batch_end = min(
                current_dir.offset + self.batch_size, len(current_dir.todo_file_paths)
            )

            for i in range(current_dir.offset, batch_end):
                file_path = current_dir.todo_file_paths[i]
                doc = self._process_file(file_path)
                if doc:
                    yield doc

            # Update offset
            current_dir.offset = batch_end

            # Check if done with current directory
            if current_dir.offset >= len(current_dir.todo_file_paths):
                checkpoint.current_directory = None

            return checkpoint

        # Get next directory to scan
        if not checkpoint.todo_directories:
            # All done
            checkpoint.has_more = False
            return checkpoint

        # Pop next directory and scan it
        dir_path = checkpoint.todo_directories.pop(0)

        try:
            entries = os.listdir(dir_path)
            file_paths = []
            subdirs = []

            for entry in entries:
                entry_path = os.path.join(dir_path, entry)
                if os.path.isfile(entry_path):
                    # Check if file should be excluded
                    if not self._should_exclude_file(entry):
                        file_paths.append(entry_path)
                elif os.path.isdir(entry_path) and self.recursive:
                    subdirs.append(entry_path)

            # Add subdirectories to todo list (breadth-first)
            checkpoint.todo_directories.extend(subdirs)

            # Set up current directory for file processing
            if file_paths:
                checkpoint.current_directory = CurrentDirectory(
                    path=dir_path,
                    todo_file_paths=file_paths,
                    offset=0,
                )

        except Exception as e:
            logger.error(f"Failed to list directory {dir_path}: {e}")

        return checkpoint
