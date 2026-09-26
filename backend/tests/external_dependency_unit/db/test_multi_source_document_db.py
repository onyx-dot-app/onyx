from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import delete, event
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    element_update_permissions,
)
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document as ConnectorDocument
from onyx.connectors.models import IndexAttemptMetadata, InputType
from onyx.db.document import (
    get_document_source_types,
    get_document_source_types_after_cc_pair_removal,
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
from onyx.indexing.indexing_pipeline import _upsert_documents_in_db
from onyx.kg.models import KGStage
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

TEST_METADATA_KEY = "permission-owner"


def _add_cc_pair(
    db_session: Session,
    source: DocumentSource,
    status: ConnectorCredentialPairStatus,
    unique: str,
    access_type: AccessType = AccessType.PUBLIC,
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
        access_type=access_type,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.flush()
    return cc_pair


def _run_permission_update(
    connector_id: int,
    credential_id: int,
    source: DocumentSource,
    document_id: str,
    group_id: str,
) -> None:
    assert element_update_permissions(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        permissions=DocExternalAccess(
            external_access=ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids={group_id},
                is_public=False,
            ),
            doc_id=document_id,
        ),
        source_type_str=source.value,
        connector_id=connector_id,
        credential_id=credential_id,
    )


def _write_permissions(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    source: DocumentSource,
    document_id: str,
    group_id: str,
) -> None:
    _run_permission_update(
        cc_pair.connector_id,
        cc_pair.credential_id,
        source,
        document_id,
        group_id,
    )
    db_session.expire_all()


def _add_document_relationship(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    document_id: str,
    *,
    has_been_indexed: bool,
) -> None:
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=document_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=has_been_indexed,
        )
    )
    db_session.commit()


def _assert_document_group(
    db_session: Session,
    document_id: str,
    source: DocumentSource,
    group_id: str,
) -> None:
    db_session.expire_all()
    document = db_session.get(Document, document_id)
    assert document is not None
    assert document.external_user_group_ids == [
        build_ext_group_name_for_onyx(group_id, source)
    ]


def _index_sharepoint_document(
    db_session: Session,
    document_id: str,
    semantic_identifier: str,
    group_id: str,
) -> None:
    _upsert_documents_in_db(
        [
            ConnectorDocument(
                id=document_id,
                source=DocumentSource.SHAREPOINT,
                sections=[],
                semantic_identifier=semantic_identifier,
                metadata={},
                external_access=ExternalAccess(
                    external_user_emails={"sharepoint@example.com"},
                    external_user_group_ids={group_id},
                    is_public=True,
                ),
                doc_metadata={TEST_METADATA_KEY: semantic_identifier},
            )
        ],
        IndexAttemptMetadata(connector_id=0, credential_id=0),
        db_session,
    )


def _add_document_with_onedrive_acl(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    document_id: str,
    *,
    has_been_indexed: bool,
) -> None:
    db_session.add(
        Document(
            id=document_id,
            semantic_id=document_id,
            kg_stage=KGStage.NOT_STARTED,
            external_user_emails=[],
            external_user_group_ids=[
                build_ext_group_name_for_onyx("onedrive", DocumentSource.ONEDRIVE)
            ],
            is_public=False,
        )
    )
    db_session.flush()
    _add_document_relationship(
        db_session,
        cc_pair,
        document_id,
        has_been_indexed=has_been_indexed,
    )


def _delete_test_data(
    db_session: Session,
    document_ids: list[str],
    cc_pairs: list[ConnectorCredentialPair],
) -> None:
    connector_ids = [cc_pair.connector_id for cc_pair in cc_pairs]
    credential_ids = [cc_pair.credential_id for cc_pair in cc_pairs]
    db_session.execute(
        delete(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.id.in_(document_ids)
        )
    )
    db_session.execute(delete(Document).where(Document.id.in_(document_ids)))
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id.in_(connector_ids)
        )
    )
    db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.commit()


def test_document_sources_follow_relationship_rows_and_add_marks_stale(
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
        assert get_document_source_types(db_session, [document_id]) == {
            document_id: (
                DocumentSource.GOOGLE_DRIVE,
                DocumentSource.SHAREPOINT,
                DocumentSource.WEB,
            )
        }
        assert get_document_source_types_after_cc_pair_removal(
            db_session,
            document_id,
            cc_pairs[0].connector_id,
            cc_pairs[0].credential_id,
        ) == (
            DocumentSource.GOOGLE_DRIVE,
            DocumentSource.SHAREPOINT,
        )

        upsert_document_by_connector_credential_pair(
            db_session,
            cc_pairs[3].connector_id,
            cc_pairs[3].credential_id,
            [document_id],
        )
        db_session.refresh(document)

        assert document.last_modified is not None
        assert document.last_modified > old_modified
        assert get_document_source_types(db_session, [document_id]) == {
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


def test_onedrive_permission_write_takes_ownership_from_sharepoint(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"permission-owner-{unique}"
    sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    db_session.commit()

    try:
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-initial",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.SHAREPOINT,
            "sharepoint-initial",
        )

        _add_document_relationship(
            db_session,
            onedrive,
            document_id,
            has_been_indexed=True,
        )
        _write_permissions(
            db_session,
            onedrive,
            DocumentSource.ONEDRIVE,
            document_id,
            "onedrive",
        )
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-later",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.ONEDRIVE,
            "onedrive",
        )
    finally:
        _delete_test_data(db_session, [document_id], [sharepoint, onedrive])


def test_sharepoint_never_overwrites_indexed_onedrive_permissions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"onedrive-first-{unique}"
    sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    document = Document(
        id=document_id,
        semantic_id=document_id,
        kg_stage=KGStage.NOT_STARTED,
    )
    db_session.add(document)
    db_session.flush()
    _add_document_relationship(
        db_session,
        onedrive,
        document_id,
        has_been_indexed=True,
    )
    _add_document_relationship(
        db_session,
        sharepoint,
        document_id,
        has_been_indexed=True,
    )

    try:
        _write_permissions(
            db_session,
            onedrive,
            DocumentSource.ONEDRIVE,
            document_id,
            "onedrive-first",
        )
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.ONEDRIVE,
            "onedrive-first",
        )
    finally:
        _delete_test_data(db_session, [document_id], [sharepoint, onedrive])


def test_sharepoint_indexing_preserves_owned_onedrive_permissions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"indexed-permission-owner-{unique}"
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    db_session.commit()

    try:
        _add_document_with_onedrive_acl(
            db_session,
            onedrive,
            document_id,
            has_been_indexed=True,
        )

        _index_sharepoint_document(
            db_session,
            document_id,
            "updated-by-sharepoint",
            "sharepoint",
        )

        db_session.expire_all()
        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.semantic_id == "updated-by-sharepoint"
        assert document.doc_metadata == {TEST_METADATA_KEY: "updated-by-sharepoint"}
        assert document.external_user_emails == []
        assert document.external_user_group_ids == [
            build_ext_group_name_for_onyx("onedrive", DocumentSource.ONEDRIVE)
        ]
        assert document.is_public is False
    finally:
        _delete_test_data(db_session, [document_id], [onedrive])


@pytest.mark.parametrize(
    ("onedrive_access_type", "has_been_indexed"),
    [
        (AccessType.PUBLIC, True),
        (AccessType.SYNC, False),
    ],
)
def test_sharepoint_indexing_writes_acls_without_owned_onedrive_permissions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    onedrive_access_type: AccessType,
    has_been_indexed: bool,
) -> None:
    unique = uuid4().hex
    document_id = f"index-non-owner-{unique}"
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        onedrive_access_type,
    )
    db_session.commit()

    try:
        _add_document_with_onedrive_acl(
            db_session,
            onedrive,
            document_id,
            has_been_indexed=has_been_indexed,
        )

        _index_sharepoint_document(
            db_session,
            document_id,
            "updated-by-sharepoint",
            "sharepoint",
        )

        db_session.expire_all()
        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == ["sharepoint@example.com"]
        assert document.external_user_group_ids == ["sharepoint"]
        assert document.is_public is True
    finally:
        _delete_test_data(db_session, [document_id], [onedrive])


@pytest.mark.parametrize(
    ("onedrive_access_type", "has_been_indexed"),
    [
        (AccessType.PUBLIC, True),
        (AccessType.SYNC, False),
    ],
)
def test_nonqualifying_onedrive_relationship_does_not_suppress_sharepoint(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    onedrive_access_type: AccessType,
    has_been_indexed: bool,
) -> None:
    unique = uuid4().hex
    document_id = f"nonqualifying-onedrive-{unique}"
    sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        onedrive_access_type,
    )
    db_session.commit()

    try:
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-initial",
        )
        _add_document_relationship(
            db_session,
            onedrive,
            document_id,
            has_been_indexed=has_been_indexed,
        )
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-later",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.SHAREPOINT,
            "sharepoint-later",
        )
    finally:
        _delete_test_data(db_session, [document_id], [sharepoint, onedrive])


def test_removing_onedrive_relationship_restores_sharepoint_writes(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"permission-owner-removal-{unique}"
    sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.DELETING,
        unique,
        AccessType.SYNC,
    )
    db_session.commit()

    try:
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-initial",
        )
        _add_document_relationship(
            db_session,
            onedrive,
            document_id,
            has_been_indexed=True,
        )
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-skipped",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.SHAREPOINT,
            "sharepoint-initial",
        )

        db_session.execute(
            delete(DocumentByConnectorCredentialPair).where(
                DocumentByConnectorCredentialPair.id == document_id,
                DocumentByConnectorCredentialPair.connector_id == onedrive.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == onedrive.credential_id,
            )
        )
        db_session.commit()
        _write_permissions(
            db_session,
            sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "sharepoint-restored",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.SHAREPOINT,
            "sharepoint-restored",
        )
    finally:
        _delete_test_data(db_session, [document_id], [sharepoint, onedrive])


def test_same_source_permissions_remain_last_writer_wins(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"same-source-{unique}"
    first_sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        f"first-{unique}",
        AccessType.SYNC,
    )
    second_sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        f"second-{unique}",
        AccessType.SYNC,
    )
    db_session.commit()

    try:
        _write_permissions(
            db_session,
            first_sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "first",
        )
        _write_permissions(
            db_session,
            second_sharepoint,
            DocumentSource.SHAREPOINT,
            document_id,
            "second",
        )
        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.SHAREPOINT,
            "second",
        )
    finally:
        _delete_test_data(
            db_session,
            [document_id],
            [first_sharepoint, second_sharepoint],
        )


def test_document_lock_prevents_concurrent_sharepoint_final_write(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"concurrent-permissions-{unique}"
    sharepoint = _add_cc_pair(
        db_session,
        DocumentSource.SHAREPOINT,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    onedrive = _add_cc_pair(
        db_session,
        DocumentSource.ONEDRIVE,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
        AccessType.SYNC,
    )
    document = Document(
        id=document_id,
        semantic_id=document_id,
        kg_stage=KGStage.NOT_STARTED,
    )
    db_session.add(document)
    db_session.flush()
    _add_document_relationship(
        db_session,
        onedrive,
        document_id,
        has_been_indexed=True,
    )
    _add_document_relationship(
        db_session,
        sharepoint,
        document_id,
        has_been_indexed=True,
    )
    onedrive_ids = (onedrive.connector_id, onedrive.credential_id)
    sharepoint_ids = (sharepoint.connector_id, sharepoint.credential_id)

    lock_acquired = Event()
    release_onedrive = Event()

    def pause_first_locked_writer(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if lock_acquired.is_set() or "FOR UPDATE" not in statement:
            return
        if "document" not in statement or current_thread().name != "onedrive-writer_0":
            return
        lock_acquired.set()
        if not release_onedrive.wait(timeout=5):
            raise TimeoutError("Timed out while holding the document lock")

    engine = db_session.get_bind()
    event.listen(engine, "after_cursor_execute", pause_first_locked_writer)
    try:
        with ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="onedrive-writer",
        ) as onedrive_executor:
            onedrive_result = onedrive_executor.submit(
                _run_permission_update,
                *onedrive_ids,
                DocumentSource.ONEDRIVE,
                document_id,
                "onedrive-concurrent",
            )
            assert lock_acquired.wait(timeout=5)

            with ThreadPoolExecutor(max_workers=1) as sharepoint_executor:
                sharepoint_result = sharepoint_executor.submit(
                    _run_permission_update,
                    *sharepoint_ids,
                    DocumentSource.SHAREPOINT,
                    document_id,
                    "sharepoint-concurrent",
                )
                with pytest.raises(FutureTimeoutError):
                    sharepoint_result.result(timeout=0.2)

                release_onedrive.set()
                onedrive_result.result(timeout=5)
                sharepoint_result.result(timeout=5)

        _assert_document_group(
            db_session,
            document_id,
            DocumentSource.ONEDRIVE,
            "onedrive-concurrent",
        )
    finally:
        release_onedrive.set()
        event.remove(engine, "after_cursor_execute", pause_first_locked_writer)
        _delete_test_data(db_session, [document_id], [sharepoint, onedrive])
