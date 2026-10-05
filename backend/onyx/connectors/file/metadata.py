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


def file_document_id(file_id: str, metadata_document_id: str | None) -> str:
    """The id of the document a file gives: the id its metadata sets, else
    one derived from the file id. Uploaded bytes get a new file id."""
    return metadata_document_id or f"{_DOCUMENT_ID_PREFIX}{file_id}"


def load_zip_metadata(
    zip_metadata_file_id: str | None, zip_metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """The connector's metadata by file name, from the metadata file or the
    deprecated inline dict. A metadata file that cannot be read counts as
    empty, as it does for indexing."""
    if zip_metadata_file_id:
        try:
            metadata_io = get_default_file_store().read_file(
                file_id=zip_metadata_file_id, mode="b"
            )
            loaded_metadata = json.loads(metadata_io.read())
            if isinstance(loaded_metadata, list):
                return {d["filename"]: d for d in loaded_metadata}
            return loaded_metadata
        except Exception as e:
            logger.warning("Failed to load metadata from file store: %s", e)
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
