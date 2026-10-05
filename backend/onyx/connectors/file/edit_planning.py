"""The planning rule of the file connector: an edit indexes only the files
whose document is new or changed, and prunes only when a document is gone.

A file's document id comes from its metadata entry ("id"), else from its file
id. Uploaded bytes always get a new file id, so a re-upload gives a new
document unless the metadata sets the id. The rule reads each file's content
hash and both metadata files, which ``load_file_planning_data`` loads.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    process_onyx_metadata,
)
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_staging import (
    added_file_ids,
    ensure_files_staged_for_edit,
)
from onyx.connectors.file.metadata import (
    file_document_id,
    load_zip_metadata,
    zip_metadata_entry,
)
from onyx.connectors.planning_rule import (
    ConnectorChangeOverride,
    PlanningData,
    RuleSteps,
)
from onyx.db.file_record import get_stored_file_facts
from onyx.file_store.models import StoredFileFacts

_FILE_LOCATIONS = "file_locations"
_FILE_NAMES = "file_names"
_ZIP_METADATA_FILE_ID = "zip_metadata_file_id"
_ZIP_METADATA = "zip_metadata"
# file_names is display-only; the default rules keep it COSMETIC.
_PLANNED_FIELDS = frozenset({_FILE_LOCATIONS, _ZIP_METADATA_FILE_ID, _ZIP_METADATA})


class FilePlanningData(PlanningData):
    # By file id. A file without a record gives no document and is absent.
    files: dict[str, StoredFileFacts]
    # Metadata entries by file name, as indexing reads them.
    old_metadata: dict[str, Any]
    new_metadata: dict[str, Any]


class _FileDocument(BaseModel):
    """The document one stored file gives under one config."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    document_id: str
    facts: StoredFileFacts
    metadata_entry: dict[str, Any]


def _documents(
    file_ids: list[str],
    files: dict[str, StoredFileFacts],
    zip_metadata: dict[str, Any],
) -> dict[str, _FileDocument]:
    documents: dict[str, _FileDocument] = {}
    for file_id in file_ids:
        facts = files.get(file_id)
        if facts is None:
            continue
        entry = zip_metadata_entry(zip_metadata, facts.display_name)
        documents[file_id] = _FileDocument(
            file_id=file_id,
            document_id=file_document_id(
                file_id, process_onyx_metadata(entry)[0].document_id
            ),
            facts=facts,
            metadata_entry=entry,
        )
    return documents


def _is_unchanged(new: _FileDocument, old: _FileDocument | None) -> bool:
    """True when ``old`` already indexed the document ``new`` gives. A file
    with an unknown hash counts as changed."""
    if old is None:
        return False
    same_content = old.file_id == new.file_id or (
        new.facts.content_sha256 is not None and old.facts == new.facts
    )
    return (
        same_content
        and old.document_id == new.document_id
        and old.metadata_entry == new.metadata_entry
    )


def _backfill_config(
    new: LocalFileConnectorConfig, file_ids: list[str]
) -> dict[str, Any]:
    # Missing names fall back to the file id, as the file list endpoint does.
    names = dict(zip(new.file_locations, new.file_names or [], strict=False))
    return new.model_copy(
        update={
            _FILE_LOCATIONS: file_ids,
            _FILE_NAMES: [names.get(file_id, file_id) for file_id in file_ids],
        }
    ).model_dump(mode="json")


def file_planning_rule(
    old: LocalFileConnectorConfig,
    new: LocalFileConnectorConfig,
    data: FilePlanningData,
) -> ConnectorChangeOverride | None:
    if (old.file_locations, old.zip_metadata_file_id, old.zip_metadata) == (
        new.file_locations,
        new.zip_metadata_file_id,
        new.zip_metadata,
    ):
        return None

    old_documents = _documents(old.file_locations, data.files, data.old_metadata)
    new_documents = _documents(new.file_locations, data.files, data.new_metadata)
    old_by_document_id = {doc.document_id: doc for doc in old_documents.values()}
    file_ids_to_index = [
        file_id
        for file_id, doc in new_documents.items()
        if not _is_unchanged(
            doc,
            old_documents.get(file_id) or old_by_document_id.get(doc.document_id),
        )
    ]
    gone_document_ids = set(old_by_document_id) - {
        doc.document_id for doc in new_documents.values()
    }
    return ConnectorChangeOverride(
        rule_steps=RuleSteps(
            field_names=_PLANNED_FIELDS,
            backfill_config=(
                _backfill_config(new, file_ids_to_index) if file_ids_to_index else None
            ),
            prune=bool(gone_document_ids),
        )
    )


def load_file_planning_data(
    db_session: Session,
    cc_pair_id: int,
    old: LocalFileConnectorConfig,
    new: LocalFileConnectorConfig,
) -> FilePlanningData:
    """Raises ``OnyxError`` when the edit adds a file that was not staged for
    this pair (see ``edit_staging``)."""
    ensure_files_staged_for_edit(db_session, cc_pair_id, added_file_ids(old, new))
    old_metadata = load_zip_metadata(old.zip_metadata_file_id, old.zip_metadata)
    same_metadata = (old.zip_metadata_file_id, old.zip_metadata) == (
        new.zip_metadata_file_id,
        new.zip_metadata,
    )
    return FilePlanningData(
        files=get_stored_file_facts(
            db_session, list(dict.fromkeys([*old.file_locations, *new.file_locations]))
        ),
        old_metadata=old_metadata,
        new_metadata=(
            old_metadata
            if same_metadata
            else load_zip_metadata(new.zip_metadata_file_id, new.zip_metadata)
        ),
    )
