"""External dependency unit tests for the doc_created_at backfill (acquisition half).

Validates that the pruning-side collection of a source creation time works:
1. extract_ids_from_runnable_connector captures doc_created_at from slim docs.
2. backfill_docs_created_at__no_commit persists it and bumps last_modified so the
   metadata sync task will propagate it.
3. The bump only happens when the value actually changes (no re-sync churn).

Uses a mock SlimConnector plus a real PostgreSQL database.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import HierarchyNode, InputType, SlimDocument
from onyx.db.document import backfill_docs_created_at__no_commit
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
)
from onyx.db.models import Document as DbDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.kg.models import KGStage

_CREATED_AT = datetime(2021, 6, 1, tzinfo=timezone.utc)


class _MockSlimConnector(SlimConnector):
    """Yields a single batch of the given slim docs."""

    def __init__(self, docs: list[SlimDocument]) -> None:
        self._docs = docs

    def load_credentials(
        self,
        credentials: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        return None

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        batch: list[SlimDocument | HierarchyNode] = list(self._docs)
        yield batch


def test_extraction_captures_doc_created_at() -> None:
    docs = [
        SlimDocument(id="doc-a", doc_created_at=_CREATED_AT),
        SlimDocument(id="doc-b"),  # no creation time supplied
    ]
    result = extract_ids_from_runnable_connector(
        _MockSlimConnector(docs), callback=None
    )

    # both docs are enumerated for pruning...
    assert result.raw_id_to_parent.keys() == {"doc-a", "doc-b"}
    # ...but only the one carrying a value contributes a created_at
    assert result.id_to_created_at == {"doc-a": _CREATED_AT}


def _make_cc_pair(db_session: Session) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"created-at-backfill-{uuid4().hex[:8]}",
        source=DocumentSource.GURU,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
    )
    credential = Credential(
        source=DocumentSource.GURU, credential_json={}, admin_public=True
    )
    db_session.add_all([connector, credential])
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=connector.name,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


@pytest.fixture
def cc_pairs(
    db_session: Session,
) -> Generator[list[ConnectorCredentialPair], None, None]:
    pairs = [_make_cc_pair(db_session), _make_cc_pair(db_session)]
    yield pairs
    connector_ids = [p.connector_id for p in pairs]
    credential_ids = [p.credential_id for p in pairs]
    db_session.rollback()
    db_session.execute(
        delete(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.connector_id.in_(connector_ids)
        )
    )
    db_session.execute(
        delete(DbDocument).where(DbDocument.id.like("created-at-backfill-%"))
    )
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id.in_(connector_ids)
        )
    )
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
    db_session.commit()


def _add_doc(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    chunk_count: int | None,
    doc_created_at: datetime | None,
    last_modified: datetime | None = None,
) -> str:
    doc_id = f"created-at-backfill-{uuid4().hex[:8]}"
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=chunk_count,
            doc_created_at=doc_created_at,
            last_modified=last_modified or datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()
    return doc_id


def _backfill(
    db_session: Session, cc_pair: ConnectorCredentialPair, doc_id: str
) -> DbDocument:
    backfill_docs_created_at__no_commit(
        {doc_id: _CREATED_AT},
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        db_session=db_session,
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(DbDocument, doc_id)
    assert row is not None
    return row


def test_backfill_sets_created_at_and_bumps_last_modified(
    db_session: Session, cc_pairs: list[ConnectorCredentialPair]
) -> None:
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    doc_id = _add_doc(db_session, cc_pairs[0], 2, None, old_modified)

    row = _backfill(db_session, cc_pairs[0], doc_id)

    assert row.doc_created_at == _CREATED_AT
    # dirtied so the metadata sync task (last_modified > last_synced) picks it up
    assert row.last_modified is not None and row.last_modified > old_modified


def test_backfill_is_noop_when_value_unchanged(
    db_session: Session, cc_pairs: list[ConnectorCredentialPair]
) -> None:
    doc_id = _add_doc(db_session, cc_pairs[0], 2, _CREATED_AT)
    before = db_session.get(DbDocument, doc_id)
    assert before is not None
    last_modified_before = before.last_modified

    row = _backfill(db_session, cc_pairs[0], doc_id)

    # value already matched → row not touched, so no needless re-sync
    assert row.doc_created_at == _CREATED_AT
    assert row.last_modified == last_modified_before


def test_backfill_skips_doc_without_chunk_count(
    db_session: Session, cc_pairs: list[ConnectorCredentialPair]
) -> None:
    # An unknown chunk count makes the metadata-sync update a no-op, so the
    # backfill must NOT persist created_at (which would falsely mark it synced);
    # it's left for a later sweep once indexing sets the count.
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    doc_id = _add_doc(db_session, cc_pairs[0], None, None, old_modified)

    row = _backfill(db_session, cc_pairs[0], doc_id)

    # not persisted, not dirtied → retried on a later sweep
    assert row.doc_created_at is None
    assert row.last_modified == old_modified


def test_backfill_skips_doc_of_another_cc_pair(
    db_session: Session, cc_pairs: list[ConnectorCredentialPair]
) -> None:
    # A pruning connector that reports another connector's doc id must not
    # rewrite that doc's created_at.
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    doc_id = _add_doc(db_session, cc_pairs[0], 2, None, old_modified)

    row = _backfill(db_session, cc_pairs[1], doc_id)

    assert row.doc_created_at is None
    assert row.last_modified == old_modified
