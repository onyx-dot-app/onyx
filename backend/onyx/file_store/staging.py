from collections.abc import Callable
from typing import Any
from typing import IO

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


# (content, content_type) -> file_id
RawFileCallback = Callable[[IO[bytes], str], str]


def stage_raw_file(
    content: IO,
    content_type: str,
    *,
    metadata: dict[str, Any],
) -> str:
    """Persist raw bytes to the file store with FileOrigin.INDEXING_STAGING.

    `metadata` is attached to the file_record so that downstream promotion
    (in docprocessing) and orphan reaping (TTL janitor) can locate the file
    by its originating context.
    """
    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=content,
        display_name=None,
        file_origin=FileOrigin.INDEXING_STAGING,
        file_type=content_type,
        file_metadata=metadata,
    )
    return file_id


def build_raw_file_callback(
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
) -> RawFileCallback:
    """Build a per-attempt callback that connectors can invoke to opt in to
    raw-file persistence. The closure binds the attempt-level context as the
    staging metadata so the connector only needs to pass per-call info
    (bytes, content_type) and gets back a file_id to attach to its Document.
    """
    metadata: dict[str, Any] = {
        "index_attempt_id": index_attempt_id,
        "cc_pair_id": cc_pair_id,
        "tenant_id": tenant_id,
    }

    def _callback(content: IO[bytes], content_type: str) -> str:
        return stage_raw_file(
            content=content,
            content_type=content_type,
            metadata=metadata,
        )

    return _callback
