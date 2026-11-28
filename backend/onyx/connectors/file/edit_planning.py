"""The planning rule of the file connector: an edit indexes only the files
whose document is new or changed, and prunes only when a document is gone.

A file's document id comes from its metadata entry ("id"), else from its file
id. Uploaded bytes always get a new file id, so a re-upload gives a new
document unless the metadata sets the id. Files that share a document id give
one document, so a change to any of them re-indexes all of them. The rule
reads each file's content hash and both metadata files, which
``load_file_planning_data`` loads.
"""

from typing import Any

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
    ZipMetadataError,
    file_document_id,
    load_zip_metadata,
    zip_metadata_entry,
)
from onyx.connectors.file.models import FileDocument, FilePlanningData
from onyx.connectors.planning_rule import (
    ConnectorChangeOverride,
    RuleSteps,
)
from onyx.db.file_record import get_stored_file_facts
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import StoredFileFacts

_FILE_LOCATIONS = "file_locations"
_FILE_NAMES = "file_names"
_ZIP_METADATA_FILE_ID = "zip_metadata_file_id"
_ZIP_METADATA = "zip_metadata"
# file_names is display-only; the default rules keep it COSMETIC.
_PLANNED_FIELDS = frozenset({_FILE_LOCATIONS, _ZIP_METADATA_FILE_ID, _ZIP_METADATA})


def _documents_by_id(
    file_ids: list[str],
    files: dict[str, StoredFileFacts],
    zip_metadata: dict[str, Any],
) -> dict[str, list[FileDocument]]:
    """The files that give each document id, in config order."""
    documents: dict[str, list[FileDocument]] = {}
    for file_id in dict.fromkeys(file_ids):
        facts = files.get(file_id)
        if facts is None:
            continue
        entry = zip_metadata_entry(zip_metadata, facts.display_name)
        document_id = file_document_id(
            file_id, process_onyx_metadata(entry)[0].document_id
        )
        documents.setdefault(document_id, []).append(
            FileDocument(
                file_id=file_id,
                document_id=document_id,
                facts=facts,
                metadata_entry=entry,
            )
        )
    return documents


def _is_unchanged(new: FileDocument, old: FileDocument) -> bool:
    """True when ``old`` gives the same document content as ``new``. A file
    with an unknown hash counts as changed."""
    same_content = old.file_id == new.file_id or (
        new.facts.content_sha256 is not None and old.facts == new.facts
    )
    return same_content and old.metadata_entry == new.metadata_entry


def _group_is_unchanged(new: list[FileDocument], old: list[FileDocument]) -> bool:
    """Indexing keeps the fields of one file of a shared document id, so a
    group is unchanged only when each of its files is."""
    return len(new) == len(old) and all(
        _is_unchanged(new_doc, old_doc)
        for new_doc, old_doc in zip(new, old, strict=True)
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

    old_documents = _documents_by_id(old.file_locations, data.files, data.old_metadata)
    new_documents = _documents_by_id(new.file_locations, data.files, data.new_metadata)
    changed_file_ids = {
        doc.file_id
        for document_id, group in new_documents.items()
        if not _group_is_unchanged(group, old_documents.get(document_id, []))
        for doc in group
    }
    file_ids_to_index = [
        file_id
        for file_id in dict.fromkeys(new.file_locations)
        if file_id in changed_file_ids
    ]
    gone_document_ids = old_documents.keys() - new_documents.keys()
    return ConnectorChangeOverride(
        rule_steps=RuleSteps(
            field_names=_PLANNED_FIELDS,
            backfill_config=(
                _backfill_config(new, file_ids_to_index) if file_ids_to_index else None
            ),
            prune=bool(gone_document_ids),
        )
    )


def _strict_zip_metadata(config: LocalFileConnectorConfig) -> dict[str, Any]:
    try:
        return load_zip_metadata(
            config.zip_metadata_file_id, config.zip_metadata, strict=True
        )
    except ZipMetadataError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{e} The edit cannot be planned without the connector's metadata.",
        ) from e


def load_file_planning_data(
    db_session: Session,
    cc_pair_id: int,
    old: LocalFileConnectorConfig,
    new: LocalFileConnectorConfig,
) -> FilePlanningData:
    """Raises ``OnyxError`` when the edit adds a file that was not staged for
    this pair (see ``edit_staging``), or when a metadata file cannot be read
    or has a wrong shape. Without its metadata, a plan can miss changed
    documents."""
    ensure_files_staged_for_edit(db_session, cc_pair_id, added_file_ids(old, new))
    old_metadata = _strict_zip_metadata(old)
    same_metadata = (old.zip_metadata_file_id, old.zip_metadata) == (
        new.zip_metadata_file_id,
        new.zip_metadata,
    )
    return FilePlanningData(
        files=get_stored_file_facts(
            db_session, list(dict.fromkeys([*old.file_locations, *new.file_locations]))
        ),
        old_metadata=old_metadata,
        new_metadata=old_metadata if same_metadata else _strict_zip_metadata(new),
    )
