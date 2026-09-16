from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.document import (
    get_indexable_document_sources,
    get_indexable_document_sources_after_cc_pair_removal,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    Document,
    DocumentByConnectorCredentialPair,
)
from onyx.kg.models import KGStage


def _add_cc_pair(
    db_session: Session,
    source: DocumentSource,
    status: ConnectorCredentialPairStatus,
    unique: str,
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"multi-source-{source.value}-{unique}",
        source=source,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    credential = Credential(
        source=source,
        credential_json={"token": unique},
        admin_public=True,
    )
    db_session.add_all([connector, credential])
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"multi-source-{source.value}",
        status=status,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.flush()
    return cc_pair


def test_indexable_sources_aggregate_and_relationship_add_marks_stale(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"multi-source-doc-{unique}"
    old_modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    cc_pairs = [
        _add_cc_pair(
            db_session,
            DocumentSource.WEB,
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
        _add_cc_pair(
            db_session,
            DocumentSource.SHAREPOINT,
            ConnectorCredentialPairStatus.PAUSED,
            unique,
        ),
        _add_cc_pair(
            db_session,
            DocumentSource.GOOGLE_DRIVE,
            ConnectorCredentialPairStatus.INVALID,
            unique,
        ),
        _add_cc_pair(
            db_session,
            DocumentSource.GOOGLE_DRIVE,
            ConnectorCredentialPairStatus.INITIAL_INDEXING,
            unique,
        ),
    ]
    document = Document(
        id=document_id,
        semantic_id=document_id,
        kg_stage=KGStage.NOT_STARTED,
        chunk_count=1,
        last_modified=old_modified,
    )
    db_session.add(document)
    db_session.flush()
    for cc_pair in cc_pairs[:3]:
        db_session.add(
            DocumentByConnectorCredentialPair(
                id=document_id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                has_been_indexed=True,
            )
        )
    db_session.commit()

    try:
        assert get_indexable_document_sources(db_session, [document_id]) == {
            document_id: (
                DocumentSource.SHAREPOINT,
                DocumentSource.WEB,
            )
        }
        assert get_indexable_document_sources_after_cc_pair_removal(
            db_session,
            document_id,
            cc_pairs[0].connector_id,
            cc_pairs[0].credential_id,
        ) == (DocumentSource.SHAREPOINT,)

        upsert_document_by_connector_credential_pair(
            db_session,
            cc_pairs[3].connector_id,
            cc_pairs[3].credential_id,
            [document_id],
        )
        db_session.refresh(document)

        assert document.last_modified is not None
        assert document.last_modified > old_modified
        assert get_indexable_document_sources(db_session, [document_id]) == {
            document_id: (
                DocumentSource.GOOGLE_DRIVE,
                DocumentSource.SHAREPOINT,
                DocumentSource.WEB,
            )
        }
    finally:
        connector_ids = [cc_pair.connector_id for cc_pair in cc_pairs]
        credential_ids = [cc_pair.credential_id for cc_pair in cc_pairs]
        db_session.execute(
            delete(DocumentByConnectorCredentialPair).where(
                DocumentByConnectorCredentialPair.id == document_id
            )
        )
        db_session.execute(delete(Document).where(Document.id == document_id))
        db_session.execute(
            delete(ConnectorCredentialPair).where(
                ConnectorCredentialPair.connector_id.in_(connector_ids)
            )
        )
        db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
        db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
        db_session.commit()
