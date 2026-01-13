"""
Persistent Document Writer for writing indexed documents to local filesystem with
hierarchical directory structure that mirrors the source organization.
"""

import hashlib
import json
from pathlib import Path

from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PersistentDocumentWriter:
    """Writes indexed documents to local filesystem with hierarchical structure"""

    def __init__(
        self,
        base_path: str,
    ):
        self.base_path = Path(base_path)

    def write_documents(self, documents: list[Document]) -> list[str]:
        """Write documents to local filesystem, returns written file paths"""
        written_paths = []

        # Build a map of base filenames to detect duplicates
        # Key: (directory_path, base_filename) -> list of docs with that name
        filename_map: dict[tuple[Path, str], list[Document]] = {}

        for doc in documents:
            dir_path = self._build_directory_path(doc)
            base_filename = self._get_base_filename(doc)
            key = (dir_path, base_filename)
            if key not in filename_map:
                filename_map[key] = []
            filename_map[key].append(doc)

        # Now write documents, appending ID if there are duplicates
        for (dir_path, base_filename), docs in filename_map.items():
            has_duplicates = len(docs) > 1
            for doc in docs:
                try:
                    if has_duplicates:
                        # Append sanitized ID to disambiguate
                        id_suffix = self._sanitize_path_component(doc.id)
                        if len(id_suffix) > 50:
                            id_suffix = hashlib.sha256(doc.id.encode()).hexdigest()[:16]
                        filename = f"{base_filename}_{id_suffix}.json"
                    else:
                        filename = f"{base_filename}.json"

                    path = dir_path / filename
                    self._write_document(doc, path)
                    written_paths.append(str(path))
                except Exception as e:
                    logger.warning(
                        f"Failed to write document {doc.id} to persistent storage: {e}"
                    )

        return written_paths

    def _build_directory_path(self, doc: Document) -> Path:
        """Build directory path from document metadata"""
        parts = [doc.source.value]

        # Get hierarchy from doc_metadata
        hierarchy = doc.doc_metadata.get("hierarchy", {}) if doc.doc_metadata else {}
        source_path = hierarchy.get("source_path", [])

        if source_path:
            parts.extend([self._sanitize_path_component(p) for p in source_path])

        return self.base_path / "/".join(parts)

    def _get_base_filename(self, doc: Document) -> str:
        """Get base filename from semantic identifier, falling back to ID"""
        # Prefer semantic_identifier, fall back to title, then ID
        name = doc.semantic_identifier or doc.title or doc.id
        return self._sanitize_filename(name)

    def _sanitize_path_component(self, component: str) -> str:
        """Sanitize a path component for file system safety"""
        # Replace spaces with underscores
        sanitized = component.replace(" ", "_")
        # Replace other problematic characters
        sanitized = sanitized.replace("/", "_").replace("\\", "_").replace(":", "_")
        sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
        sanitized = sanitized.replace('"', "_").replace("?", "_").replace("*", "_")
        # Also handle null bytes and other control characters
        sanitized = "".join(c for c in sanitized if ord(c) >= 32)
        return sanitized.strip() or "unnamed"

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize name for use as filename"""
        sanitized = self._sanitize_path_component(name)
        if len(sanitized) > 200:
            # Keep first 150 chars + hash suffix for uniqueness
            hash_suffix = hashlib.sha256(name.encode()).hexdigest()[:16]
            return f"{sanitized[:150]}_{hash_suffix}"
        return sanitized

    def _write_document(self, doc: Document, path: Path) -> None:
        """Serialize and write document to filesystem"""
        content = {
            "id": doc.id,
            "semantic_identifier": doc.semantic_identifier,
            "title": doc.title,
            "source": doc.source.value,
            "doc_updated_at": (
                doc.doc_updated_at.isoformat() if doc.doc_updated_at else None
            ),
            "metadata": doc.metadata,
            "doc_metadata": doc.doc_metadata,
            "sections": [
                {"text": s.text if hasattr(s, "text") else None, "link": s.link}
                for s in doc.sections
            ],
            "primary_owners": [o.model_dump() for o in (doc.primary_owners or [])],
            "secondary_owners": [o.model_dump() for o in (doc.secondary_owners or [])],
        }

        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the JSON file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, default=str)

        logger.debug(f"Wrote document to {path}")


def get_persistent_document_writer() -> PersistentDocumentWriter:
    """Factory function to create a PersistentDocumentWriter with default configuration"""
    from onyx.configs.app_configs import PERSISTENT_DOCUMENT_STORAGE_PATH

    return PersistentDocumentWriter(
        base_path=PERSISTENT_DOCUMENT_STORAGE_PATH,
    )
