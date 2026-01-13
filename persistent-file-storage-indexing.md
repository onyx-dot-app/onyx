# Persistent File Storage for Indexed Documents

## Issues to Address

Extend the indexing pipeline to write every indexed document to a persistent VM file system with a hierarchical directory structure that mirrors the source organization. Initial implementation covers **Google Drive**, **Fireflies**, and **Linear** connectors.

Target structure:

```
{tenant_id}/
  google_drive/
    My Drive/
      Folder1/
        File1.json
    Shared Drive 1/
      Folder1/
        File1.json

  fireflies/
    2024-01/
      Meeting Title 1.json
      Meeting Title 2.json
    2024-02/
      Meeting Title 3.json

  linear/
    TeamName/
      DAN-123.json
      DAN-456.json
    OtherTeam/
      OTH-789.json
```

## Important Notes

### Current State of Each Connector

1. **Google Drive** (`backend/onyx/connectors/google_drive/`)
   - Most complex hierarchy: Drives → Folders → Files
   - `RetrievedDriveFile` has `parent_id` field (`models.py:114`) but full folder path not stored
   - Document creation in `doc_conversion.py:530` doesn't populate `doc_metadata`
   - Folder tracking happens during crawling via `completion_map` in checkpoint
   - **Challenge**: Must reconstruct folder paths from `parent_id` chain during crawling

2. **Fireflies** (`backend/onyx/connectors/fireflies/connector.py`)
   - Flat structure: Meeting transcripts with date/title/organizer
   - Document created in `_create_doc_from_transcript()` (line 52-116)
   - Available fields: `title`, `date`, `organizer_email`, `participants`
   - **Hierarchy approach**: Organize by year-month (e.g., `2024-01/`)
   - Currently no `doc_metadata` populated

3. **Linear** (`backend/onyx/connectors/linear/connector.py`)
   - Team-based hierarchy: Teams → Issues
   - Document created in `_process_issues()` (line 277-301)
   - Has `team.name` available from GraphQL query (line 197-199)
   - Has `identifier` (e.g., "DAN-2327") which includes team prefix
   - Currently no `doc_metadata` populated

### Integration Point

The best place to add file writing is `DocumentIndexingBatchAdapter.post_index()` in `backend/onyx/indexing/adapters/document_indexing_adapter.py:161-211`. This runs AFTER database commits and has access to:
- `context.updatable_docs` - all documents processed
- `filtered_documents` - documents that passed filtering
- `self.tenant_id` - for multi-tenant isolation
- `self.index_attempt_metadata` - connector/credential info

### Existing Patterns

- `FileStoreDocumentBatchStorage` in `backend/onyx/file_store/document_batch_storage.py` shows document serialization patterns
- `FileStore` abstraction in `backend/onyx/file_store/file_store.py` handles S3/MinIO storage with tenant isolation

## Implementation Strategy

### Phase 1: Create Core Infrastructure

**New file**: `backend/onyx/indexing/persistent_document_writer.py`

```python
class PersistentDocumentWriter:
    """Writes indexed documents to local filesystem with hierarchical structure"""

    def __init__(
        self,
        tenant_id: str,
        base_path: str,
    ):
        self.tenant_id = tenant_id
        self.base_path = Path(base_path)

    def write_documents(self, documents: list[Document]) -> list[str]:
        """Write documents to local filesystem, returns written file paths"""
        written_paths = []
        for doc in documents:
            path = self._build_path(doc)
            self._write_document(doc, path)
            written_paths.append(str(path))
        return written_paths

    def _build_path(self, doc: Document) -> Path:
        """Build hierarchical path from document metadata"""
        parts = [self.tenant_id, doc.source.value]

        # Get hierarchy from doc_metadata
        hierarchy = doc.doc_metadata.get("hierarchy", {}) if doc.doc_metadata else {}
        source_path = hierarchy.get("source_path", [])

        if source_path:
            parts.extend([self._sanitize_path_component(p) for p in source_path])

        # File name from document ID (sanitized)
        filename = f"{self._sanitize_filename(doc.id)}.json"
        return self.base_path / "/".join(parts) / filename

    def _sanitize_path_component(self, component: str) -> str:
        """Sanitize a path component for file system safety"""
        # Replace problematic characters
        sanitized = component.replace("/", "_").replace("\\", "_").replace(":", "_")
        sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
        sanitized = sanitized.replace('"', "_").replace("?", "_").replace("*", "_")
        sanitized = "".join(c for c in sanitized if ord(c) >= 32)
        return sanitized.strip() or "unnamed"

    def _sanitize_filename(self, doc_id: str) -> str:
        """Sanitize document ID for use as filename"""
        sanitized = self._sanitize_path_component(doc_id)
        if len(sanitized) > 200:
            return hashlib.sha256(doc_id.encode()).hexdigest()[:32]
        return sanitized

    def _write_document(self, doc: Document, path: Path) -> None:
        """Serialize and write document to filesystem"""
        content = {
            "id": doc.id,
            "semantic_identifier": doc.semantic_identifier,
            "title": doc.title,
            "source": doc.source.value,
            "doc_updated_at": doc.doc_updated_at.isoformat() if doc.doc_updated_at else None,
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
```

**Add configuration** to `backend/onyx/configs/app_configs.py`:

```python
PERSISTENT_DOCUMENT_STORAGE_ENABLED = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_ENABLED", ""
).lower() == "true"

# Base directory path for persistent document storage (local filesystem)
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_PATH", "/app/indexed-docs"
)
```

### Phase 2: Update Linear Connector

**File**: `backend/onyx/connectors/linear/connector.py`

Linear is the simplest - just add team name to `doc_metadata`. Modify the document creation (around line 277):

```python
# Extract team name for hierarchy
team_name = (node.get("team") or {}).get("name") or "Unknown Team"
identifier = node.get("identifier", node["id"])

documents.append(
    Document(
        id=node["id"],
        sections=typed_sections,
        source=DocumentSource.LINEAR,
        semantic_identifier=f"[{node['identifier']}] {node['title']}",
        title=node["title"],
        doc_updated_at=time_str_to_utc(node["updatedAt"]),
        doc_metadata={
            "hierarchy": {
                "source_path": [team_name],
                "team_name": team_name,
                "identifier": identifier,
            }
        },
        metadata={...},  # existing metadata
    )
)
```

### Phase 3: Update Fireflies Connector

**File**: `backend/onyx/connectors/fireflies/connector.py`

Organize by year-month. Modify `_create_doc_from_transcript()` (around line 100):

```python
# Build hierarchy based on meeting date
meeting_date = datetime.fromtimestamp(meeting_date_unix / 1000, tz=timezone.utc)
year_month = meeting_date.strftime("%Y-%m")

return Document(
    id=fireflies_id,
    sections=cast(list[TextSection | ImageSection], sections),
    source=DocumentSource.FIREFLIES,
    semantic_identifier=meeting_title,
    doc_metadata={
        "hierarchy": {
            "source_path": [year_month],
            "year_month": year_month,
            "meeting_title": meeting_title,
            "organizer_email": meeting_organizer_email,
        }
    },
    metadata={...},  # existing metadata
    doc_updated_at=meeting_date,
    primary_owners=organizer_email_user_info,
    secondary_owners=meeting_participants_email_list,
)
```

### Phase 4: Update Google Drive Connector

This is the most complex. Need to:
1. Build a folder ID → folder name mapping during crawling
2. Pass this mapping to document conversion
3. Reconstruct full folder paths

**Step 4a**: Track folder names during retrieval

**File**: `backend/onyx/connectors/google_drive/connector.py`

Add folder name tracking to the connector class:

```python
class GoogleDriveConnector:
    def __init__(self, ...):
        ...
        self._folder_id_to_name: dict[str, str] = {}
        self._folder_id_to_parent: dict[str, str | None] = {}
```

**File**: `backend/onyx/connectors/google_drive/file_retrieval.py`

When folders are retrieved/crawled, populate the mapping. In functions like `crawl_folders_for_files()` and `get_files_in_shared_drive()`, capture folder info:

```python
# When processing folders, store the mapping
folder_id_to_name[folder["id"]] = folder.get("name", "Untitled Folder")
folder_id_to_parent[folder["id"]] = folder.get("parents", [None])[0]
```

**Step 4b**: Build path reconstruction helper

**File**: `backend/onyx/connectors/google_drive/doc_conversion.py`

Add a helper function to reconstruct full paths:

```python
def build_folder_path(
    file: GoogleDriveFileType,
    folder_id_to_name: dict[str, str],
    folder_id_to_parent: dict[str, str | None],
    drive_name: str | None = None,
) -> list[str]:
    """Reconstruct the full folder path for a file"""
    path_parts = []

    # Start with the file's parent
    parent_ids = file.get("parents", [])
    parent_id = parent_ids[0] if parent_ids else None

    # Walk up the folder hierarchy
    visited = set()  # Prevent infinite loops
    while parent_id and parent_id in folder_id_to_name and parent_id not in visited:
        visited.add(parent_id)
        path_parts.insert(0, folder_id_to_name[parent_id])
        parent_id = folder_id_to_parent.get(parent_id)

    # Prepend drive name if available
    if drive_name:
        path_parts.insert(0, drive_name)

    return path_parts
```

**Step 4c**: Populate doc_metadata in document creation

Modify `_convert_drive_item_to_document()` to accept and use the folder mapping:

```python
def _convert_drive_item_to_document(
    creds: Any,
    allow_images: bool,
    size_threshold: int,
    retriever_email: str,
    file: GoogleDriveFileType,
    permission_sync_context: PermissionSyncContext | None,
    folder_id_to_name: dict[str, str] | None = None,
    folder_id_to_parent: dict[str, str | None] | None = None,
    drive_name: str | None = None,
) -> Document | ConnectorFailure | None:
    ...

    # Build folder path if mapping available
    source_path = []
    if folder_id_to_name and folder_id_to_parent:
        source_path = build_folder_path(
            file, folder_id_to_name, folder_id_to_parent, drive_name
        )
    elif drive_name:
        source_path = [drive_name]

    return Document(
        id=doc_id,
        sections=sections,
        source=DocumentSource.GOOGLE_DRIVE,
        semantic_identifier=file.get("name", ""),
        doc_metadata={
            "hierarchy": {
                "source_path": source_path,
                "drive_name": drive_name,
                "file_name": file.get("name", ""),
                "mime_type": file.get("mimeType", ""),
            }
        },
        metadata={...},  # existing
        ...
    )
```

### Phase 5: Integrate into Indexing Pipeline

**File**: `backend/onyx/indexing/adapters/document_indexing_adapter.py`

Add persistent writing at the end of `post_index()`:

```python
from onyx.configs.app_configs import PERSISTENT_DOCUMENT_STORAGE_ENABLED
from onyx.indexing.persistent_document_writer import get_persistent_document_writer

def post_index(
    self,
    context: DocumentBatchPrepareContext,
    updatable_chunk_data: list[UpdatableChunkData],
    filtered_documents: list[Document],
    result: BuildMetadataAwareChunksResult,
) -> None:
    # ... existing code ...

    self.db_session.commit()

    # Write to persistent storage if enabled
    if PERSISTENT_DOCUMENT_STORAGE_ENABLED and filtered_documents:
        try:
            writer = get_persistent_document_writer(tenant_id=self.tenant_id)
            writer.write_documents(filtered_documents)
        except Exception as e:
            # Log but don't fail indexing
            logger.warning(f"Failed to write documents to persistent storage: {e}")
```

Add factory function to `persistent_document_writer.py`:

```python
def get_persistent_document_writer(tenant_id: str) -> PersistentDocumentWriter:
    from onyx.configs.app_configs import PERSISTENT_DOCUMENT_STORAGE_PATH

    return PersistentDocumentWriter(
        tenant_id=tenant_id,
        base_path=PERSISTENT_DOCUMENT_STORAGE_PATH,
    )
```

## File Changes Summary

| File | Change |
|------|--------|
| `backend/onyx/indexing/persistent_document_writer.py` | **NEW** - Core writer class |
| `backend/onyx/configs/app_configs.py` | Add config flags |
| `backend/onyx/connectors/linear/connector.py` | Add `doc_metadata` with team hierarchy |
| `backend/onyx/connectors/fireflies/connector.py` | Add `doc_metadata` with year-month hierarchy |
| `backend/onyx/connectors/google_drive/connector.py` | Add folder name tracking |
| `backend/onyx/connectors/google_drive/file_retrieval.py` | Capture folder names during crawl |
| `backend/onyx/connectors/google_drive/doc_conversion.py` | Add path reconstruction + `doc_metadata` |
| `backend/onyx/indexing/adapters/document_indexing_adapter.py` | Call writer in `post_index()` |

