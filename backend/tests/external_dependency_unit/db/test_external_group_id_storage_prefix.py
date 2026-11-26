"""Every storage writer stores a connector's bare external group ids in the form
group sync stores, `<source>_<id>` lowercased."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.db.document import upsert_document_external_perms
from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    fetch_external_groups_for_user,
    upsert_external_groups,
)
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document as ConnectorDocument
from onyx.connectors.models import HierarchyNode as ConnectorHierarchyNode
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.enums import AccessType, HierarchyNodeType
from onyx.db.hierarchy import (
    ensure_source_node_exists,
    get_hierarchy_node_by_raw_id,
    get_source_hierarchy_node,
    update_hierarchy_node_permissions,
    upsert_hierarchy_node,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    HierarchyNode,
    User__ExternalUserGroupId,
)
from onyx.db.users import get_user_by_email
from onyx.indexing.indexing_pipeline import _upsert_documents_in_db
from tests.external_dependency_unit.conftest import delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

BARE_SOURCE = DocumentSource.BOX

# Ids a connector can yield: mixed case, the prefix text itself, and the
# separators other sources use.
RAW_GROUP_IDS = {
    "Eng-Team",
    "box_lookalike",
    "domain:example.com",
    "first+last@example.com",
    "name with spaces",
    "site::title",
}


def _stored(group_ids: set[str], source: DocumentSource) -> set[str]:
    return {build_ext_group_name_for_onyx(group_id, source) for group_id in group_ids}


def _access(group_ids: set[str], is_public: bool = False) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails={"reader@example.com"},
        external_user_group_ids=group_ids,
        is_public=is_public,
    )


@dataclass
class Seed:
    db_session: Session
    cc_pair: ConnectorCredentialPair
    source: DocumentSource
    doc_ids: list[str]
    node_raw_ids: list[str]
    user_emails: list[str]

    def new_doc_id(self) -> str:
        doc_id = f"prefix-test-doc-{uuid4().hex}"
        self.doc_ids.append(doc_id)
        return doc_id

    def new_node_raw_id(self) -> str:
        raw_id = f"prefix-test-node-{uuid4().hex}"
        self.node_raw_ids.append(raw_id)
        return raw_id

    def index_doc(self, doc_id: str, access: ExternalAccess | None) -> None:
        _upsert_documents_in_db(
            [
                ConnectorDocument(
                    id=doc_id,
                    source=self.source,
                    sections=[],
                    semantic_identifier=doc_id,
                    metadata={},
                    external_access=access,
                )
            ],
            IndexAttemptMetadata(
                connector_id=self.cc_pair.connector_id,
                credential_id=self.cc_pair.credential_id,
            ),
            self.db_session,
        )
        self.db_session.expire_all()

    def doc_sync(self, doc_id: str, access: ExternalAccess) -> None:
        upsert_document_external_perms(self.db_session, doc_id, access, self.source)
        self.db_session.expire_all()

    def upsert_node(self, raw_id: str, access: ExternalAccess | None) -> None:
        source_node = ensure_source_node_exists(self.db_session, self.source)
        upsert_hierarchy_node(
            self.db_session,
            ConnectorHierarchyNode(
                raw_node_id=raw_id,
                display_name=raw_id,
                node_type=HierarchyNodeType.FOLDER,
                external_access=access,
            ),
            source_node_id=source_node.id,
            source=self.source,
        )
        self.db_session.expire_all()

    def sync_node(self, raw_id: str, access: ExternalAccess) -> None:
        assert update_hierarchy_node_permissions(
            self.db_session,
            raw_node_id=raw_id,
            source=self.source,
            is_public=access.is_public,
            external_user_emails=list(access.external_user_emails) or None,
            external_user_group_ids=list(access.external_user_group_ids) or None,
        )
        self.db_session.expire_all()

    def doc(self, doc_id: str) -> Document:
        document = self.db_session.get(Document, doc_id)
        assert document is not None
        return document

    def node(self, raw_id: str) -> HierarchyNode:
        node = get_hierarchy_node_by_raw_id(self.db_session, raw_id, self.source)
        assert node is not None
        return node


def _seed(
    db_session: Session, source: DocumentSource, access_type: AccessType
) -> Generator[Seed, None, None]:
    had_source_node = get_source_hierarchy_node(db_session, source) is not None
    cc_pair = make_cc_pair(db_session, source=source)
    cc_pair.access_type = access_type
    db_session.commit()
    seed = Seed(db_session, cc_pair, source, [], [], [])
    try:
        yield seed
    finally:
        db_session.rollback()
        db_session.execute(
            delete(User__ExternalUserGroupId).where(
                User__ExternalUserGroupId.cc_pair_id == cc_pair.id
            )
        )
        db_session.execute(delete(Document).where(Document.id.in_(seed.doc_ids)))
        db_session.execute(
            delete(HierarchyNode).where(
                HierarchyNode.raw_node_id.in_(seed.node_raw_ids)
            )
        )
        if not had_source_node:
            db_session.execute(
                delete(HierarchyNode).where(
                    HierarchyNode.source == source,
                    HierarchyNode.node_type == HierarchyNodeType.SOURCE,
                )
            )
        users = [
            user
            for email in seed.user_emails
            if (user := get_user_by_email(email, db_session)) is not None
        ]
        if users:
            delete_test_user(db_session, *users)
        db_session.commit()
        cleanup_cc_pair(db_session, cc_pair)


@pytest.fixture
def synced(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Seed, None, None]:
    yield from _seed(db_session, BARE_SOURCE, AccessType.SYNC)


WriterCase = Callable[[Seed, ExternalAccess], list[str] | None]


def _write_indexed_doc(seed: Seed, access: ExternalAccess) -> list[str] | None:
    doc_id = seed.new_doc_id()
    seed.index_doc(doc_id, access)
    return seed.doc(doc_id).external_user_group_ids


def _write_synced_doc(seed: Seed, access: ExternalAccess) -> list[str] | None:
    doc_id = seed.new_doc_id()
    seed.doc_sync(doc_id, access)
    return seed.doc(doc_id).external_user_group_ids


def _write_indexed_node(seed: Seed, access: ExternalAccess) -> list[str] | None:
    raw_id = seed.new_node_raw_id()
    seed.upsert_node(raw_id, access)
    return seed.node(raw_id).external_user_group_ids


def _write_synced_node(seed: Seed, access: ExternalAccess) -> list[str] | None:
    raw_id = seed.new_node_raw_id()
    seed.upsert_node(raw_id, None)
    seed.sync_node(raw_id, access)
    return seed.node(raw_id).external_user_group_ids


WRITERS: dict[str, WriterCase] = {
    "indexed_doc": _write_indexed_doc,
    "doc_sync": _write_synced_doc,
    "indexed_node": _write_indexed_node,
    "synced_node": _write_synced_node,
}


@pytest.mark.parametrize("writer", WRITERS.values(), ids=WRITERS.keys())
def test_every_writer_stores_the_group_sync_form(
    synced: Seed, writer: WriterCase
) -> None:
    stored = writer(synced, _access(RAW_GROUP_IDS))

    assert set(stored or []) == _stored(RAW_GROUP_IDS, BARE_SOURCE)
    # A raw id that starts with the prefix text is still prefixed.
    assert "box_box_lookalike" in (stored or [])


@pytest.mark.parametrize("writer", WRITERS.values(), ids=WRITERS.keys())
def test_rewriting_the_same_access_is_stable(synced: Seed, writer: WriterCase) -> None:
    access = _access({"Eng-Team"})
    first = writer(synced, access)

    if writer in (_write_indexed_doc, _write_synced_doc):
        doc_id = synced.doc_ids[-1]
        synced.index_doc(doc_id, access)
        synced.doc_sync(doc_id, access)
        again = synced.doc(doc_id).external_user_group_ids
    else:
        raw_id = synced.node_raw_ids[-1]
        synced.upsert_node(raw_id, access)
        synced.sync_node(raw_id, access)
        again = synced.node(raw_id).external_user_group_ids

    assert first == again == ["box_eng-team"]


def test_public_access_stores_no_group_ids(synced: Seed) -> None:
    doc_id = synced.new_doc_id()
    synced.index_doc(doc_id, _access(set(), is_public=True))
    raw_id = synced.new_node_raw_id()
    synced.upsert_node(raw_id, _access(set(), is_public=True))

    doc = synced.doc(doc_id)
    node = synced.node(raw_id)
    assert (doc.is_public, doc.external_user_group_ids) == (True, [])
    assert (node.is_public, node.external_user_group_ids) == (True, None)


def test_missing_access_keeps_the_stored_groups(synced: Seed) -> None:
    doc_id = synced.new_doc_id()
    synced.index_doc(doc_id, _access({"Eng-Team"}))
    synced.index_doc(doc_id, None)
    raw_id = synced.new_node_raw_id()
    synced.upsert_node(raw_id, _access({"Eng-Team"}))
    synced.upsert_node(raw_id, None)

    assert synced.doc(doc_id).external_user_group_ids == ["box_eng-team"]
    assert synced.node(raw_id).external_user_group_ids == ["box_eng-team"]


def test_indexing_after_a_doc_sync_stub_keeps_one_form(synced: Seed) -> None:
    """Doc sync can store access before the first index creates the row."""
    doc_id = synced.new_doc_id()
    synced.doc_sync(doc_id, _access({"Eng-Team"}))
    stub_groups = synced.doc(doc_id).external_user_group_ids

    synced.index_doc(doc_id, _access({"Eng-Team"}))

    assert stub_groups == synced.doc(doc_id).external_user_group_ids


PERM_SYNC_SOURCES: list[DocumentSource] = sorted(
    (
        source
        for source in DocumentSource
        if get_source_perm_sync_config(source) is not None
    ),
    key=lambda source: source.value,
)


@pytest.mark.parametrize(
    "source", PERM_SYNC_SOURCES, ids=[source.value for source in PERM_SYNC_SOURCES]
)
def test_every_writer_stores_the_id_group_sync_gives_a_member(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    source: DocumentSource,
) -> None:
    with contextmanager(_seed)(db_session, source, AccessType.SYNC) as seed:
        email = f"prefix-member-{uuid4().hex}@example.com"
        seed.user_emails.append(email)
        upsert_external_groups(
            db_session,
            seed.cc_pair.id,
            [ExternalUserGroup(id="Eng-Team", user_emails=[email])],
            source,
        )
        member = get_user_by_email(email, db_session)
        assert member is not None
        member_groups = {
            row.external_user_group_id
            for row in fetch_external_groups_for_user(db_session, member.id)
        }

        for name, writer in WRITERS.items():
            stored = writer(seed, _access({"Eng-Team"}))
            assert set(stored or []) == member_groups, name


@pytest.fixture
def not_synced(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Seed, None, None]:
    yield from _seed(db_session, BARE_SOURCE, AccessType.PUBLIC)


def test_pair_without_perm_sync_stores_no_access(not_synced: Seed) -> None:
    doc_id = not_synced.new_doc_id()
    not_synced.index_doc(doc_id, _access({"Eng-Team"}))

    assert not not_synced.doc(doc_id).external_user_group_ids
