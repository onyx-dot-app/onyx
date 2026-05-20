"""Document-level metadata used during indexing.

Previously declared in the now-removed `onyx.document_index.interfaces` module.
Used by the indexing pipeline / Postgres upsert layer; not part of the search
backend interface.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from onyx.access.models import ExternalAccess


@dataclass
class DocumentMetadata:
    """
    Document information that needs to be inserted into Postgres on first time
    encountering this document during indexing across any of the connectors.
    """

    connector_id: int
    credential_id: int
    document_id: str
    semantic_identifier: str
    first_link: str
    doc_updated_at: datetime | None = None
    # Emails, not necessarily attached to users. Users may not be in Onyx.
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None
    from_ingestion_api: bool = False

    external_access: ExternalAccess | None = None
    doc_metadata: dict[str, Any] | None = None

    # The resolved database ID of the parent hierarchy node (folder/container).
    parent_hierarchy_node_id: int | None = None

    # Opt-in pointer to the persisted raw file for this document (file_store id).
    file_id: str | None = None
