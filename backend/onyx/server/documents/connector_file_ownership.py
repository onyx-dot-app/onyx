"""Which stored files a connector config may name, and which a connector's
deletion may remove. A config holds raw file-store ids, so without these
checks a caller could point a connector at any file in the tenant."""

from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.db.connector import fetch_other_connector_configs
from onyx.db.file_record import get_filerecords_by_file_ids
from onyx.db.models import FileRecord, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import (
    CONNECTOR_UPLOAD_ORIGINS,
    UPLOADED_BY_USER_ID_METADATA_KEY,
)

_METADATA_ORIGINS = frozenset({FileOrigin.CONNECTOR_METADATA})
_SOURCES_WITH_FILE_IDS = (DocumentSource.FILE, DocumentSource.GOOGLE_SITES)


def _config_file_ids(
    source: DocumentSource, config: dict[str, Any] | None
) -> dict[str, frozenset[FileOrigin]]:
    """The file ids the config names, each with the origins it may have. Reads
    the raw dict, since stored configs can predate the typed models."""
    if not config:
        return {}
    file_ids: dict[str, frozenset[FileOrigin]] = {}
    if source == DocumentSource.FILE:
        file_locations = config.get("file_locations")
        if isinstance(file_locations, list):
            for file_id in file_locations:
                if isinstance(file_id, str):
                    file_ids[file_id] = CONNECTOR_UPLOAD_ORIGINS
        metadata_file_id = config.get("zip_metadata_file_id")
        if isinstance(metadata_file_id, str) and metadata_file_id:
            file_ids[metadata_file_id] = _METADATA_ORIGINS
    elif source == DocumentSource.GOOGLE_SITES:
        zip_path = config.get("zip_path")
        if isinstance(zip_path, str):
            file_ids[zip_path] = CONNECTOR_UPLOAD_ORIGINS
    return file_ids


def _uploaded_by(record: FileRecord, user: User) -> bool:
    metadata = record.file_metadata if isinstance(record.file_metadata, dict) else {}
    return metadata.get(UPLOADED_BY_USER_ID_METADATA_KEY) == str(user.id)


def assert_connector_file_ids_owned(
    db_session: Session,
    user: User,
    source: DocumentSource,
    new_config: dict[str, Any],
    current_config: dict[str, Any] | None = None,
) -> None:
    """Every file id that ``new_config`` adds to ``current_config`` must be a
    connector upload of the right origin that ``user`` uploaded.

    Raises:
        OnyxError: An added id fails the check (INVALID_INPUT). A missing file
            and a file of another user give the same error.
    """
    wanted = _config_file_ids(source, new_config)
    bound = _config_file_ids(source, current_config)
    added = [file_id for file_id in wanted if file_id not in bound]
    if not added:
        return
    records = {
        record.file_id: record
        for record in get_filerecords_by_file_ids(added, db_session)
    }
    rejected = [
        file_id
        for file_id in added
        if (record := records.get(file_id)) is None
        or record.file_origin not in wanted[file_id]
        or not _uploaded_by(record, user)
    ]
    if rejected:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "These files were not uploaded by you for a connector. Upload them "
            f"again: {', '.join(rejected)}.",
        )


def file_ids_deletable_with_connector(
    db_session: Session, connector_id: int, file_ids: list[str]
) -> list[str]:
    """The given files that deleting this connector may remove: connector
    uploads that no other connector names."""
    records = get_filerecords_by_file_ids(file_ids, db_session)
    candidates = {
        record.file_id
        for record in records
        if record.file_origin in CONNECTOR_UPLOAD_ORIGINS
    }
    if not candidates:
        return []
    other_configs = fetch_other_connector_configs(
        db_session, connector_id, list(_SOURCES_WITH_FILE_IDS)
    )
    for source, config in other_configs:
        candidates -= set(_config_file_ids(source, config))
    return [file_id for file_id in file_ids if file_id in candidates]
