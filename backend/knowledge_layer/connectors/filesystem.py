# knowledge_layer/connectors/filesystem.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput, LoadConnector
from onyx.connectors.models import Document, TextSection

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".rst"}


class FilesystemConnector(LoadConnector):
    """Local-filesystem raw document connector for team-brain."""

    SOURCE = DocumentSource.WIKI_RAW_FS

    def __init__(self, watch_path: str) -> None:
        self.watch_path = watch_path

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        root = Path(self.watch_path)
        if not root.exists():
            return

        batch: list[Document] = []
        for entry in sorted(root.rglob("*")):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                continue

            text = entry.read_text(encoding="utf-8", errors="replace")
            doc = Document(
                id=f"wiki_raw_fs::{entry.resolve()}",
                sections=[TextSection(link=str(entry), text=text)],
                source=self.SOURCE,
                semantic_identifier=entry.name,
                metadata={"doc_type": "raw_doc", "watch_path": str(root.resolve())},
                doc_updated_at=None,
            )
            batch.append(doc)
            if len(batch) >= 16:
                yield batch
                batch = []

        if batch:
            yield batch
