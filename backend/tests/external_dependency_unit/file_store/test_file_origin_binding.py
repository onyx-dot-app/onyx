"""A caller-chosen or remote-chosen file id must not take over a stored file
of another origin, and readers check the origin of what they load."""

from collections.abc import Generator
from io import BytesIO
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.background.indexing.checkpointing_utils import load_checkpoint
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.confluence.utils import _process_image_attachment
from onyx.connectors.drupal_wiki.connector import DrupalWikiConnector
from onyx.connectors.google_site.connector import GoogleSitesConnector
from onyx.connectors.models import Document, ImageSection, TextSection
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import FileOriginConflictError, assert_file_id_writable
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.hooks.points.document_ingestion import (
    DocumentIngestionResponse,
    DocumentIngestionSection,
)
from onyx.indexing.indexing_pipeline import _apply_document_ingestion_hook

_VICTIM_BYTES = b"victim bytes"


@pytest.fixture
def store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[PostgresBackedFileStore, None, None]:
    file_store = PostgresBackedFileStore()
    file_store.initialize()
    with (
        patch(
            "onyx.file_processing.image_utils.get_default_file_store",
            return_value=file_store,
        ),
        patch(
            "onyx.background.indexing.checkpointing_utils.get_default_file_store",
            return_value=file_store,
        ),
        patch(
            "onyx.connectors.google_site.connector.get_default_file_store",
            return_value=file_store,
        ),
    ):
        yield file_store


def _save(
    store: PostgresBackedFileStore, file_id: str, origin: FileOrigin, data: bytes
) -> None:
    store.save_file(
        content=BytesIO(data),
        display_name=file_id,
        file_origin=origin,
        file_type="application/json",
        file_id=file_id,
    )


def _assert_untouched(
    store: PostgresBackedFileStore, file_id: str, origin: FileOrigin
) -> None:
    assert store.read_file_record(file_id).file_origin == origin
    assert store.read_file(file_id).read() == _VICTIM_BYTES


def test_save_file_refuses_to_overwrite_another_origin(
    store: PostgresBackedFileStore,
) -> None:
    file_id = f"checkpoint_{uuid4().hex}.json"
    _save(store, file_id, FileOrigin.INDEXING_CHECKPOINT, _VICTIM_BYTES)

    with pytest.raises(FileOriginConflictError):
        _save(store, file_id, FileOrigin.CONNECTOR, b"attacker bytes")
    _assert_untouched(store, file_id, FileOrigin.INDEXING_CHECKPOINT)

    _save(store, file_id, FileOrigin.INDEXING_CHECKPOINT, b"next checkpoint")
    assert store.read_file(file_id).read() == b"next checkpoint"


def _assert_absent(store: PostgresBackedFileStore, file_id: str) -> None:
    with pytest.raises(RuntimeError):
        store.read_file_record(file_id)


def test_confluence_attachment_id_cannot_name_a_file_id(
    store: PostgresBackedFileStore,
) -> None:
    # A future checkpoint id: no record holds it yet.
    target_id = f"checkpoint_{uuid4().hex}.json"

    result = _process_image_attachment(
        {"id": target_id, "title": "a.png"},
        b"attacker bytes",
        "image/png",
        "https://wiki.example.com",
    )

    assert result.error is None and result.file_name != target_id
    _assert_absent(store, target_id)


def test_drupal_attachment_id_cannot_name_a_file_id(
    store: PostgresBackedFileStore,
) -> None:
    target_id = f"iab/{uuid4().hex}/0.json"
    connector = DrupalWikiConnector(
        base_url="https://wiki.example.com",
        include_attachments=True,
        allow_images=True,
    )

    with patch.object(
        DrupalWikiConnector, "_download_attachment", return_value=b"attacker"
    ):
        sections, error = connector._process_attachment(
            {"id": target_id, "fileName": "a.png", "fileSize": 10}, 1, "/d"
        )

    assert error is None and len(sections) == 1
    _assert_absent(store, target_id)


def test_checkpoint_of_another_origin_is_not_loaded(
    store: PostgresBackedFileStore,
) -> None:
    attempt_id = 900_000_000 + int(uuid4().int % 1_000_000)
    _save(
        store,
        f"checkpoint_{attempt_id}.json",
        FileOrigin.CONNECTOR,
        b'{"has_more": true}',
    )

    with pytest.raises(ValueError, match="not an indexing checkpoint"):
        load_checkpoint(attempt_id, connector=object())  # ty: ignore[invalid-argument-type]


def test_google_sites_zip_of_another_origin_is_not_read(
    store: PostgresBackedFileStore,
) -> None:
    chat_upload_id = str(uuid4())
    _save(store, chat_upload_id, FileOrigin.CHAT_UPLOAD, _VICTIM_BYTES)
    connector = GoogleSitesConnector(
        zip_path=chat_upload_id, base_url="https://sites.example.com"
    )

    with pytest.raises(ValueError, match="not a connector upload"):
        next(iter(connector.load_from_state()))


def test_ingestion_hook_cannot_add_an_image_it_was_not_sent(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,  # noqa: ARG001
) -> None:
    doc = Document(
        id=f"doc-{uuid4().hex}",
        source=DocumentSource.FILE,
        semantic_identifier="doc",
        metadata={},
        sections=[TextSection(text="body"), ImageSection(image_file_id="own-image")],
    )
    response = DocumentIngestionResponse(
        sections=[
            DocumentIngestionSection(text="body"),
            DocumentIngestionSection(image_file_id="own-image"),
            DocumentIngestionSection(image_file_id="someone-elses-chat-upload"),
        ]
    )

    def _execute_hook(**_: Any) -> DocumentIngestionResponse:
        return response

    with patch("onyx.indexing.indexing_pipeline.execute_hook", _execute_hook):
        [applied] = _apply_document_ingestion_hook([doc])

    assert [
        s.image_file_id for s in applied.sections if isinstance(s, ImageSection)
    ] == ["own-image"]


def test_writable_check_locks_the_id_until_the_record_commits(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,  # noqa: ARG001
) -> None:
    file_id = f"checkpoint_{uuid4().hex}.json"
    with get_session_with_current_tenant() as first:
        assert_file_id_writable(file_id, FileOrigin.INDEXING_CHECKPOINT, first)
        with get_session_with_current_tenant() as second:
            second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                assert_file_id_writable(file_id, FileOrigin.CONNECTOR, second)
        first.rollback()
