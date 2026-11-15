"""How the file connector reads its zip metadata and names its documents.
Indexing and edit planning share these, so a plan predicts the documents a
run gives."""

import json
import os
from typing import Any

from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCUMENT_ID_PREFIX = "FILE_CONNECTOR__"
_FILENAME_KEY = "filename"


def file_document_id(file_id: str, metadata_document_id: str | None) -> str:
    """The id of the document a file gives: the id its metadata sets, else
    one derived from the file id. Uploaded bytes get a new file id."""
    return metadata_document_id or f"{_DOCUMENT_ID_PREFIX}{file_id}"


class ZipMetadataError(Exception):
    """The connector's metadata file cannot be read or has a wrong shape."""


def _metadata_by_file_name(loaded_metadata: Any) -> dict[str, Any]:
    """Accepts a dict by file name, or a list of entries that each name
    their file."""
    if isinstance(loaded_metadata, dict):
        return loaded_metadata
    if isinstance(loaded_metadata, list) and all(
        isinstance(entry, dict) and isinstance(entry.get(_FILENAME_KEY), str)
        for entry in loaded_metadata
    ):
        return {entry[_FILENAME_KEY]: entry for entry in loaded_metadata}
    raise ZipMetadataError(
        "The metadata file must hold a JSON object, or a list of objects "
        f"that each have a '{_FILENAME_KEY}'."
    )


def _read_zip_metadata_file(zip_metadata_file_id: str) -> dict[str, Any]:
    try:
        metadata_io = get_default_file_store().read_file(
            file_id=zip_metadata_file_id, mode="b"
        )
        loaded_metadata = json.loads(metadata_io.read())
    except Exception as e:
        raise ZipMetadataError(
            f"The metadata file {zip_metadata_file_id} cannot be read."
        ) from e
    return _metadata_by_file_name(loaded_metadata)


def load_zip_metadata(
    zip_metadata_file_id: str | None,
    zip_metadata: dict[str, Any] | None,
    strict: bool = False,
) -> dict[str, Any]:
    """The connector's metadata by file name, from the metadata file or the
    deprecated inline dict.

    Raises:
        ZipMetadataError: ``strict`` and the metadata file cannot be read or
            has a wrong shape. Without ``strict``, such a file counts as
            empty, as it does for indexing.
    """
    if zip_metadata_file_id:
        try:
            return _read_zip_metadata_file(zip_metadata_file_id)
        except ZipMetadataError:
            if strict:
                raise
            logger.exception("Failed to load metadata from file store")
            return {}
    if zip_metadata:
        logger.warning(
            "Using deprecated inline zip_metadata dict. Re-upload files to use the new file store format."
        )
        return zip_metadata
    return {}


def zip_metadata_entry(
    zip_metadata: dict[str, Any], display_name: str
) -> dict[str, Any]:
    return zip_metadata.get(display_name, {}) or zip_metadata.get(
        os.path.basename(display_name), {}
    )
