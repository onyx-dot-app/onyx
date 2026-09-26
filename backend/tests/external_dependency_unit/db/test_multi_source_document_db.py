from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.db.document import upsert_document_external_perms
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.credentials import delete_credential
from onyx.db.document import (
    delete_all_documents_by_connector_credential_pair__no_commit,
    delete_document_by_connector_credential_pair__no_commit,
    get_document_source_types,
    get_document_source_types_after_cc_pair_removal,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    Document,
    DocumentByConnectorCredentialPair,
)
from onyx.kg.models import KGStage
from onyx.server.documents.models import ConnectorCredentialPairIdentifier

CONCURRENT_TEST_TIMEOUT = 10


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
        _delete_test_data(db_session, [document_id], cc_pairs)


def test_normal_acl_update_preserves_legacy_until_all_contributions_are_known(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"multi-source-acl-{unique}"
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
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
        _add_cc_pair(
            db_session,
            DocumentSource.GOOGLE_DRIVE,
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
    ]
    db_session.add(
        Document(
            id=document_id,
            semantic_id=document_id,
            kg_stage=KGStage.NOT_STARTED,
            external_user_emails=["legacy@example.com"],
            external_user_group_ids=["legacy-group"],
            is_public=True,
        )
    )
    for cc_pair in cc_pairs:
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
        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pairs[0].connector_id,
            cc_pairs[0].credential_id,
            ExternalAccess({"a@example.com"}, {"group-a"}, False),
            DocumentSource.WEB,
        )
        document = db_session.get(Document, document_id)
        assert document is not None
        assert set(document.external_user_emails or []) == {
            "legacy@example.com",
            "a@example.com",
        }
        assert set(document.external_user_group_ids or []) == {
            "legacy-group",
            build_ext_group_name_for_onyx("group-a", DocumentSource.WEB),
        }
        assert document.is_public is True

        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pairs[1].connector_id,
            cc_pairs[1].credential_id,
            ExternalAccess({"b@example.com"}, {"group-b"}, True),
            DocumentSource.SHAREPOINT,
        )
        db_session.refresh(document)
        assert set(document.external_user_emails or []) == {
            "legacy@example.com",
            "a@example.com",
            "b@example.com",
        }
        assert set(document.external_user_group_ids or []) == {
            "legacy-group",
            build_ext_group_name_for_onyx("group-a", DocumentSource.WEB),
            build_ext_group_name_for_onyx("group-b", DocumentSource.SHAREPOINT),
        }
        assert document.is_public is True

        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pairs[2].connector_id,
            cc_pairs[2].credential_id,
            ExternalAccess.empty(),
            DocumentSource.GOOGLE_DRIVE,
        )
        db_session.refresh(document)
        assert set(document.external_user_emails or []) == {
            "a@example.com",
            "b@example.com",
        }
        assert set(document.external_user_group_ids or []) == {
            build_ext_group_name_for_onyx("group-a", DocumentSource.WEB),
            build_ext_group_name_for_onyx("group-b", DocumentSource.SHAREPOINT),
        }
        assert document.is_public is True

        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pairs[0].connector_id,
            cc_pairs[0].credential_id,
            ExternalAccess.empty(),
            DocumentSource.WEB,
        )
        db_session.refresh(document)
        assert set(document.external_user_emails or []) == {"b@example.com"}
        assert set(document.external_user_group_ids or []) == {
            build_ext_group_name_for_onyx("group-b", DocumentSource.SHAREPOINT)
        }
        assert document.is_public is True
    finally:
        _delete_test_data(db_session, [document_id], cc_pairs)


def test_relationship_deletion_wipes_acl_when_a_remaining_contribution_is_unknown(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"unknown-delete-acl-{unique}"
    cc_pairs = [
        _add_cc_pair(
            db_session,
            source,
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        )
        for source in (
            DocumentSource.WEB,
            DocumentSource.SHAREPOINT,
            DocumentSource.GOOGLE_DRIVE,
        )
    ]
    db_session.add(
        Document(
            id=document_id,
            semantic_id=document_id,
            external_user_emails=["legacy@example.com"],
            external_user_group_ids=["legacy-group"],
            is_public=True,
        )
    )
    for cc_pair in cc_pairs:
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
        for cc_pair, email, source in zip(
            cc_pairs[:2],
            ["removed@example.com", "known@example.com"],
            [DocumentSource.WEB, DocumentSource.SHAREPOINT],
            strict=True,
        ):
            upsert_document_external_perms(
                db_session,
                document_id,
                cc_pair.connector_id,
                cc_pair.credential_id,
                ExternalAccess({email}, set(), False),
                source,
            )

        delete_document_by_connector_credential_pair__no_commit(
            db_session,
            document_id,
            ConnectorCredentialPairIdentifier(
                connector_id=cc_pairs[0].connector_id,
                credential_id=cc_pairs[0].credential_id,
            ),
        )
        db_session.commit()

        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == []
        assert document.external_user_group_ids == []
        assert document.is_public is False
    finally:
        _delete_test_data(db_session, [document_id], cc_pairs)


def test_concurrent_source_acl_updates_create_document_and_preserve_contributions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"concurrent-acl-{unique}"
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
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
    ]
    db_session.commit()
    assert db_session.get(Document, document_id) is None

    start = Barrier(len(cc_pairs))

    def update_source(
        connector_id: int,
        credential_id: int,
        source: DocumentSource,
        access: ExternalAccess,
    ) -> None:
        with get_session_with_current_tenant() as worker_session:
            start.wait(timeout=CONCURRENT_TEST_TIMEOUT)
            upsert_document_external_perms(
                worker_session,
                document_id,
                connector_id,
                credential_id,
                access,
                source,
            )

    try:
        sources_and_access = [
            (
                DocumentSource.WEB,
                ExternalAccess({"web@example.com"}, {"web-group"}, False),
            ),
            (
                DocumentSource.SHAREPOINT,
                ExternalAccess({"sharepoint@example.com"}, {"sharepoint-group"}, True),
            ),
        ]
        with ThreadPoolExecutor(max_workers=len(cc_pairs)) as executor:
            futures = [
                executor.submit(
                    update_source,
                    cc_pair.connector_id,
                    cc_pair.credential_id,
                    source,
                    access,
                )
                for cc_pair, (source, access) in zip(
                    cc_pairs,
                    sources_and_access,
                    strict=True,
                )
            ]
            for future in futures:
                future.result(timeout=CONCURRENT_TEST_TIMEOUT)

        db_session.expire_all()
        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.semantic_id == document_id
        assert set(document.external_user_emails or []) == {
            "web@example.com",
            "sharepoint@example.com",
        }
        assert set(document.external_user_group_ids or []) == {
            build_ext_group_name_for_onyx("web-group", DocumentSource.WEB),
            build_ext_group_name_for_onyx(
                "sharepoint-group", DocumentSource.SHAREPOINT
            ),
        }
        assert document.is_public is True

        for cc_pair, (source, access) in zip(cc_pairs, sources_and_access, strict=True):
            relationship = db_session.get(
                DocumentByConnectorCredentialPair,
                (document_id, cc_pair.connector_id, cc_pair.credential_id),
            )
            assert relationship is not None
            assert relationship.has_been_indexed is False
            assert set(relationship.external_user_emails or []) == (
                access.external_user_emails
            )
            assert set(relationship.external_user_group_ids or []) == {
                build_ext_group_name_for_onyx(group_id, source)
                for group_id in access.external_user_group_ids
            }
            assert relationship.is_public is access.is_public
    finally:
        _delete_test_data(db_session, [document_id], cc_pairs)


def test_single_source_external_acl_replacement_creates_unindexed_relationship(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"single-source-acl-{unique}"
    cc_pair = _add_cc_pair(
        db_session,
        DocumentSource.WEB,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
    )
    db_session.commit()

    try:
        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pair.connector_id,
            cc_pair.credential_id,
            ExternalAccess({"first@example.com"}, {"first-group"}, True),
            DocumentSource.WEB,
        )
        relationship = db_session.get(
            DocumentByConnectorCredentialPair,
            (document_id, cc_pair.connector_id, cc_pair.credential_id),
        )
        assert relationship is not None
        assert relationship.has_been_indexed is False

        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pair.connector_id,
            cc_pair.credential_id,
            ExternalAccess({"second@example.com"}, set(), False),
            DocumentSource.WEB,
        )
        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == ["second@example.com"]
        assert document.external_user_group_ids == []
        assert document.is_public is False
    finally:
        _delete_test_data(db_session, [document_id], [cc_pair])


def test_github_raw_group_starting_with_source_prefix_remains_distinct(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"group-prefix-collision-{unique}"
    cc_pair = _add_cc_pair(
        db_session,
        DocumentSource.GITHUB,
        ConnectorCredentialPairStatus.ACTIVE,
        unique,
    )
    db_session.commit()

    try:
        upsert_document_external_perms(
            db_session,
            document_id,
            cc_pair.connector_id,
            cc_pair.credential_id,
            ExternalAccess(set(), {"team", "github_team"}, False),
            DocumentSource.GITHUB,
        )

        relationship = db_session.get(
            DocumentByConnectorCredentialPair,
            (document_id, cc_pair.connector_id, cc_pair.credential_id),
        )
        document = db_session.get(Document, document_id)
        assert relationship is not None
        assert document is not None
        expected_groups = ["github_github_team", "github_team"]
        assert relationship.external_user_group_ids == expected_groups
        assert document.external_user_group_ids == expected_groups
    finally:
        _delete_test_data(db_session, [document_id], [cc_pair])


def test_deleting_cc_pair_rejects_permission_update(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"deleting-acl-{unique}"
    cc_pair = _add_cc_pair(
        db_session,
        DocumentSource.WEB,
        ConnectorCredentialPairStatus.DELETING,
        unique,
    )
    db_session.commit()

    try:
        with pytest.raises(ValueError, match="being deleted"):
            upsert_document_external_perms(
                db_session,
                document_id,
                cc_pair.connector_id,
                cc_pair.credential_id,
                ExternalAccess({"late@example.com"}, set(), False),
                DocumentSource.WEB,
            )
        db_session.rollback()
        assert db_session.get(Document, document_id) is None

        db_session.add(Document(id=document_id, semantic_id=document_id))
        db_session.commit()
        with pytest.raises(ValueError, match="being deleted"):
            upsert_document_by_connector_credential_pair(
                db_session,
                cc_pair.connector_id,
                cc_pair.credential_id,
                [document_id],
            )
        db_session.rollback()
        assert (
            db_session.get(
                DocumentByConnectorCredentialPair,
                (document_id, cc_pair.connector_id, cc_pair.credential_id),
            )
            is None
        )
    finally:
        _delete_test_data(db_session, [document_id], [cc_pair])


def test_bulk_relationship_deletion_recomputes_retained_document_acl(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"bulk-delete-acl-{unique}"
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
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
    ]
    db_session.commit()

    try:
        for cc_pair, email, source in zip(
            cc_pairs,
            ["removed@example.com", "retained@example.com"],
            [DocumentSource.WEB, DocumentSource.SHAREPOINT],
            strict=True,
        ):
            upsert_document_external_perms(
                db_session,
                document_id,
                cc_pair.connector_id,
                cc_pair.credential_id,
                ExternalAccess({email}, set(), False),
                source,
            )

        delete_all_documents_by_connector_credential_pair__no_commit(
            db_session,
            cc_pairs[0].connector_id,
            cc_pairs[0].credential_id,
        )
        db_session.commit()

        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == ["retained@example.com"]
    finally:
        _delete_test_data(db_session, [document_id], cc_pairs)


def test_forced_credential_deletion_recomputes_retained_document_acl(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"credential-delete-acl-{unique}"
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
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        ),
    ]
    removed_connector_id = cc_pairs[0].connector_id
    db_session.commit()

    try:
        for cc_pair, email, source in zip(
            cc_pairs,
            ["removed@example.com", "retained@example.com"],
            [DocumentSource.WEB, DocumentSource.SHAREPOINT],
            strict=True,
        ):
            upsert_document_external_perms(
                db_session,
                document_id,
                cc_pair.connector_id,
                cc_pair.credential_id,
                ExternalAccess({email}, set(), False),
                source,
            )

        delete_credential(cc_pairs[0].credential_id, db_session, force=True)

        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == ["retained@example.com"]
    finally:
        _delete_test_data(db_session, [document_id], [cc_pairs[1]])
        db_session.execute(
            delete(Connector).where(Connector.id == removed_connector_id)
        )
        db_session.commit()


def test_forced_credential_deletion_wipes_acl_for_unknown_remaining_contribution(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    unique = uuid4().hex
    document_id = f"credential-delete-unknown-acl-{unique}"
    cc_pairs = [
        _add_cc_pair(
            db_session,
            source,
            ConnectorCredentialPairStatus.ACTIVE,
            unique,
        )
        for source in (
            DocumentSource.WEB,
            DocumentSource.SHAREPOINT,
            DocumentSource.GOOGLE_DRIVE,
        )
    ]
    removed_connector_id = cc_pairs[0].connector_id
    db_session.commit()

    try:
        for cc_pair, email, source in zip(
            cc_pairs[:2],
            ["removed@example.com", "known@example.com"],
            [DocumentSource.WEB, DocumentSource.SHAREPOINT],
            strict=True,
        ):
            upsert_document_external_perms(
                db_session,
                document_id,
                cc_pair.connector_id,
                cc_pair.credential_id,
                ExternalAccess({email}, set(), False),
                source,
            )
        upsert_document_by_connector_credential_pair(
            db_session,
            cc_pairs[2].connector_id,
            cc_pairs[2].credential_id,
            [document_id],
        )

        delete_credential(cc_pairs[0].credential_id, db_session, force=True)

        document = db_session.get(Document, document_id)
        assert document is not None
        assert document.external_user_emails == []
        assert document.external_user_group_ids == []
        assert document.is_public is False
    finally:
        _delete_test_data(db_session, [document_id], cc_pairs[1:])
        db_session.execute(
            delete(Connector).where(Connector.id == removed_connector_id)
        )
        db_session.commit()
