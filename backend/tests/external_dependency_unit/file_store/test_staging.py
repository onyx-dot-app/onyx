"""External dependency tests for onyx.file_store.staging.

Exercises the raw-file persistence hook used by the docfetching pipeline
against a real file store (Postgres + MinIO/S3), since mocking the store
would defeat the point of verifying that metadata round-trips through
FileRecord.
"""

from collections.abc import Generator
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.connectors.interfaces import BaseConnector
from onyx.db.file_record import delete_filerecord_by_file_id
from onyx.db.file_record import get_filerecord_by_file_id
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import build_raw_file_callback
from onyx.file_store.staging import stage_raw_file


@pytest.fixture(scope="function")
def cleanup_file_ids(
    db_session: Session,
) -> Generator[list[str], None, None]:
    created: list[str] = []
    yield created
    file_store = get_default_file_store()
    for fid in created:
        try:
            file_store.delete_file(fid)
        except Exception:
            delete_filerecord_by_file_id(file_id=fid, db_session=db_session)
            db_session.commit()


def test_stage_raw_file_persists_with_origin_and_metadata(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    cleanup_file_ids: list[str],
) -> None:
    """stage_raw_file writes a FileRecord with INDEXING_STAGING origin and
    round-trips the provided metadata verbatim."""
    metadata: dict[str, Any] = {
        "index_attempt_id": 42,
        "cc_pair_id": 7,
        "tenant_id": "tenant-abc",
        "extra": "payload",
    }
    content_bytes = b"hello raw file"
    content_type = "application/pdf"

    file_id = stage_raw_file(
        content=BytesIO(content_bytes),
        content_type=content_type,
        metadata=metadata,
    )
    cleanup_file_ids.append(file_id)
    db_session.commit()

    record = get_filerecord_by_file_id(file_id=file_id, db_session=db_session)
    assert record.file_origin == FileOrigin.INDEXING_STAGING
    assert record.file_type == content_type
    assert record.file_metadata == metadata


def test_build_raw_file_callback_binds_attempt_context_per_call(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    cleanup_file_ids: list[str],
) -> None:
    """The callback returned by build_raw_file_callback must bind the
    attempt-level context into every FileRecord it produces, without
    leaking state across invocations."""
    callback = build_raw_file_callback(
        index_attempt_id=1001,
        cc_pair_id=202,
        tenant_id="tenant-xyz",
    )

    file_id_a = callback(BytesIO(b"alpha"), "text/plain")
    file_id_b = callback(BytesIO(b"beta"), "application/octet-stream")
    cleanup_file_ids.extend([file_id_a, file_id_b])
    db_session.commit()

    assert file_id_a != file_id_b

    for fid, expected_content_type in (
        (file_id_a, "text/plain"),
        (file_id_b, "application/octet-stream"),
    ):
        record = get_filerecord_by_file_id(file_id=fid, db_session=db_session)
        assert record.file_origin == FileOrigin.INDEXING_STAGING
        assert record.file_type == expected_content_type
        assert record.file_metadata == {
            "index_attempt_id": 1001,
            "cc_pair_id": 202,
            "tenant_id": "tenant-xyz",
        }


def test_set_raw_file_callback_on_base_connector() -> None:
    """set_raw_file_callback must install the callback as an instance
    attribute usable by the connector."""

    class _MinimalConnector(BaseConnector):
        def load_credentials(
            self,
            credentials: dict[str, Any],  # noqa: ARG002
        ) -> dict[str, Any] | None:
            return None

    connector = _MinimalConnector()
    assert connector.raw_file_callback is None

    sentinel_file_id = f"sentinel-{uuid4().hex[:8]}"

    def _fake_callback(_content: Any, _content_type: str) -> str:
        return sentinel_file_id

    connector.set_raw_file_callback(_fake_callback)

    assert connector.raw_file_callback is _fake_callback
    assert connector.raw_file_callback(BytesIO(b""), "text/plain") == sentinel_file_id
