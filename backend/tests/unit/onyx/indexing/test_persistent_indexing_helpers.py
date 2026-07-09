"""Unit tests for the PERSISTENT_INDEXING catch-all helpers in
`onyx.indexing.persistent_indexing`."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.indexing.persistent_indexing import build_generic_connector_failure
from onyx.indexing.persistent_indexing import record_generic_failure


def _make_doc(
    doc_id: str = "doc-1", link: str | None = "https://example.com/doc-1"
) -> Document:
    return Document(
        id=doc_id,
        semantic_identifier="test",
        source=DocumentSource.FILE,
        sections=[TextSection(text="some text", link=link)],
        metadata={},
    )


# -----------------------------------------------------------------------------
# build_generic_connector_failure
# -----------------------------------------------------------------------------


def test_build_generic_connector_failure_from_document() -> None:
    doc = _make_doc()
    exc = RuntimeError("kaboom")

    failure = build_generic_connector_failure(exc=exc, document=doc)

    assert failure.failed_document is not None
    assert failure.failed_entity is None
    assert failure.failed_document.document_id == "doc-1"
    assert failure.failed_document.document_link == "https://example.com/doc-1"
    assert failure.failure_message == "kaboom"
    assert failure.exception is exc


def test_build_generic_connector_failure_document_without_sections() -> None:
    # Document with no sections should still produce a valid failure with no link.
    doc = Document(
        id="doc-empty",
        semantic_identifier="empty",
        source=DocumentSource.FILE,
        sections=[],
        metadata={},
    )

    failure = build_generic_connector_failure(exc=ValueError("oops"), document=doc)

    assert failure.failed_document is not None
    assert failure.failed_document.document_id == "doc-empty"
    assert failure.failed_document.document_link is None


def test_build_generic_connector_failure_from_entity() -> None:
    exc = RuntimeError("entity boom")
    failure = build_generic_connector_failure(
        exc=exc, entity_id="docfetching:slack:cc_pair_42:batch_3"
    )

    assert failure.failed_entity is not None
    assert failure.failed_document is None
    assert failure.failed_entity.entity_id == "docfetching:slack:cc_pair_42:batch_3"
    assert failure.failure_message == "entity boom"
    assert failure.exception is exc


def test_build_generic_connector_failure_rejects_both_args() -> None:
    with pytest.raises(ValueError):
        build_generic_connector_failure(
            exc=RuntimeError("x"),
            document=_make_doc(),
            entity_id="some-entity",
        )


def test_build_generic_connector_failure_rejects_neither_arg() -> None:
    with pytest.raises(ValueError):
        build_generic_connector_failure(exc=RuntimeError("x"))


def test_build_generic_connector_failure_with_base_exception() -> None:
    # BaseException (not Exception) — exception field should be None since
    # the BaseModel field is typed `Exception | None`.
    exc = KeyboardInterrupt()  # subclass of BaseException, not Exception
    failure = build_generic_connector_failure(exc=exc, entity_id="x")

    assert failure.failed_entity is not None
    assert failure.exception is None


# -----------------------------------------------------------------------------
# record_generic_failure
# -----------------------------------------------------------------------------


def test_record_generic_failure_persists_via_create_index_attempt_error() -> None:
    failure = build_generic_connector_failure(
        exc=RuntimeError("write me"), entity_id="entity-1"
    )

    with (
        patch(
            "onyx.indexing.persistent_indexing.get_session_with_current_tenant"
        ) as mock_session_ctx,
        patch(
            "onyx.indexing.persistent_indexing.create_index_attempt_error"
        ) as mock_create,
    ):
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session

        record_generic_failure(
            index_attempt_id=7,
            cc_pair_id=11,
            source=DocumentSource.SLACK,
            tenant_id="tenant-a",
            failure=failure,
        )

        mock_create.assert_called_once_with(7, 11, failure, mock_session)


def test_record_generic_failure_swallows_db_errors() -> None:
    failure = build_generic_connector_failure(
        exc=RuntimeError("db down"), entity_id="entity-1"
    )

    with (
        patch(
            "onyx.indexing.persistent_indexing.get_session_with_current_tenant"
        ) as mock_session_ctx,
        patch(
            "onyx.indexing.persistent_indexing.create_index_attempt_error",
            side_effect=Exception("db exploded"),
        ),
    ):
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session

        # Must not raise: the recovery path itself can't kill the attempt.
        record_generic_failure(
            index_attempt_id=7,
            cc_pair_id=11,
            source=DocumentSource.SLACK,
            tenant_id="tenant-a",
            failure=failure,
        )
