"""Stages the files of a file connector edit (see
``onyx.connectors.file.edit_staging``)."""

import json
from io import BytesIO
from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.configs.constants import ONYX_METADATA_FILENAME, DocumentSource, FileOrigin
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_staging import ensure_files_staged_for_edit
from onyx.connectors.file.metadata import ZipMetadataError, load_zip_metadata
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.file_record import get_stored_file_facts
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import STAGED_FOR_CC_PAIR_METADATA_KEY
from onyx.file_store.file_store import get_default_file_store
from onyx.server.documents.connector import upload_files
from onyx.server.documents.models import FileUploadResponse


def _current_file_config(
    db_session: Session, cc_pair_id: int
) -> LocalFileConnectorConfig:
    cc_pair = get_connector_credential_pair_from_id(
        db_session, cc_pair_id, eager_load_connector=True
    )
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.CONNECTOR_NOT_FOUND,
            f"Connector-credential pair {cc_pair_id} does not exist.",
        )
    if cc_pair.connector.source != DocumentSource.FILE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only a file connector takes uploaded files.",
        )
    return LocalFileConnectorConfig.model_validate(
        cc_pair.connector.connector_specific_config
    )


def _read_metadata_strictly(
    zip_metadata_file_id: str | None, zip_metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """A merge must not drop the entries of a file it cannot read."""
    try:
        return load_zip_metadata(zip_metadata_file_id, zip_metadata, strict=True)
    except ZipMetadataError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e


def _base_metadata(
    db_session: Session,
    cc_pair_id: int,
    current: LocalFileConnectorConfig,
    draft_zip_metadata_file_id: str | None,
) -> dict[str, Any]:
    """The metadata a new zip merges into: the draft's when the edit already
    staged one, else the pair's current metadata."""
    if (
        draft_zip_metadata_file_id is None
        or draft_zip_metadata_file_id == current.zip_metadata_file_id
    ):
        return _read_metadata_strictly(
            current.zip_metadata_file_id, current.zip_metadata
        )
    ensure_files_staged_for_edit(db_session, cc_pair_id, [draft_zip_metadata_file_id])
    return _read_metadata_strictly(draft_zip_metadata_file_id, None)


def stage_file_connector_upload(
    db_session: Session,
    cc_pair_id: int,
    files: list[UploadFile],
    draft_zip_metadata_file_id: str | None = None,
) -> FileUploadResponse:
    """Saves the uploads as files staged for an edit of the pair. An upload
    with the content, name and type of a current file returns that file's id,
    so its document keeps its id. A zip's metadata is merged into the draft's
    metadata (``draft_zip_metadata_file_id``: the pair's file or one staged
    earlier in this edit), else into the pair's current metadata, and staged
    as a new metadata file. Without a zip, the draft's metadata file id comes
    back unchanged.

    Raises:
        OnyxError: The pair is not a file connector, the draft's metadata
            file was not staged for this pair's edit, or a metadata file to
            merge cannot be read or has a wrong shape (INVALID_INPUT).
    """
    current = _current_file_config(db_session, cc_pair_id)
    base_metadata = _base_metadata(
        db_session, cc_pair_id, current, draft_zip_metadata_file_id
    )
    uploaded = upload_files(
        files, FileOrigin.CONNECTOR, staged_for_cc_pair_id=cc_pair_id
    )
    file_store = get_default_file_store()

    facts = get_stored_file_facts(
        db_session, [*current.file_locations, *uploaded.file_paths]
    )
    current_file_ids = {
        facts[file_id]: file_id
        for file_id in current.file_locations
        if file_id in facts and facts[file_id].content_sha256 is not None
    }
    file_ids: list[str] = []
    for file_id in uploaded.file_paths:
        current_file_id = current_file_ids.get(facts[file_id])
        if current_file_id is None:
            file_ids.append(file_id)
            continue
        file_store.delete_file(file_id)
        file_ids.append(current_file_id)

    zip_metadata_file_id = draft_zip_metadata_file_id
    if uploaded.zip_metadata_file_id is not None:
        merged_metadata = base_metadata | _read_metadata_strictly(
            uploaded.zip_metadata_file_id, None
        )
        zip_metadata_file_id = file_store.save_file(
            content=BytesIO(json.dumps(merged_metadata).encode("utf-8")),
            display_name=ONYX_METADATA_FILENAME,
            file_origin=FileOrigin.CONNECTOR_METADATA,
            file_type="application/json",
            file_metadata={STAGED_FOR_CC_PAIR_METADATA_KEY: cc_pair_id},
        )
        file_store.delete_file(uploaded.zip_metadata_file_id)

    return FileUploadResponse(
        file_paths=file_ids,
        file_names=uploaded.file_names,
        zip_metadata_file_id=zip_metadata_file_id,
    )
