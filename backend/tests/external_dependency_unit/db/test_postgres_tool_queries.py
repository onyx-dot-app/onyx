"""Tests for the Postgres tool DB query layer (documents + hierarchy nodes).

Covers the correctness traps this layer exists to handle: ACL/ownership
scoping, hidden-document exclusion, multi-cc_pair dedup (rows and counts),
grouped counts, LIKE-wildcard escaping, date/owner filters, and MIT vs EE
hierarchy access filtering.

Everything is scoped by a per-test uuid tag embedded in semantic ids /
display names, since the tests run against a real shared Postgres.
"""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from ee.onyx.db.postgres_tool import (
    _hierarchy_node_access_filter as ee_hierarchy_filter,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import Tag, TimeRange
from onyx.db.enums import AccessType, HierarchyNodeType
from onyx.db.models import (
    ConnectorCredentialPair,
    Document__Tag,
    DocumentByConnectorCredentialPair,
    DocumentSet,
    DocumentSet__ConnectorCredentialPair,
    HierarchyNode,
)
from onyx.db.models import Document as DbDocument
from onyx.db.models import Tag as TagRow
from onyx.db.postgres_tool import (
    DocumentGroupBy,
    _count_hierarchy_nodes,
    _query_hierarchy_nodes,
    count_documents_for_tool,
    count_documents_grouped_for_tool,
    count_hierarchy_nodes_for_tool,
    query_documents_for_tool,
    query_hierarchy_nodes_for_tool,
)
from onyx.db.postgres_tool import (
    _hierarchy_node_access_filter as mit_hierarchy_filter,
)
from onyx.db.postgres_tool_models import DocumentScope
from onyx.kg.models import KGStage
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _make_doc(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    doc_id: str,
    semantic_id: str,
    *,
    hidden: bool = False,
    is_public: bool = False,
    external_user_emails: list[str] | None = None,
    external_user_group_ids: list[str] | None = None,
    primary_owners: list[str] | None = None,
    doc_updated_at: datetime | None = None,
    doc_created_at: datetime | None = None,
    parent_hierarchy_node_id: int | None = None,
) -> None:
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=semantic_id,
            hidden=hidden,
            is_public=is_public,
            external_user_emails=external_user_emails,
            external_user_group_ids=external_user_group_ids,
            primary_owners=primary_owners,
            doc_updated_at=doc_updated_at,
            doc_created_at=doc_created_at,
            parent_hierarchy_node_id=parent_hierarchy_node_id,
            kg_stage=KGStage.NOT_STARTED,
        )
    )
    db_session.flush()
    _link_doc(db_session, cc_pair, doc_id)


def _link_doc(
    db_session: Session, cc_pair: ConnectorCredentialPair, doc_id: str
) -> None:
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.flush()


def _sids(rows: list[tuple[DbDocument, DocumentSource]]) -> set[str]:
    return {d.semantic_id for d, _ in rows}


@dataclass
class DocEnv:
    tag: str
    alice: str
    group: str
    cc_public: ConnectorCredentialPair  # WEB, access_type PUBLIC
    cc_sync: ConnectorCredentialPair  # GOOGLE_DRIVE, access_type SYNC
    node: HierarchyNode


@pytest.fixture()
def doc_env(db_session: Session) -> Generator[DocEnv, None, None]:
    tag = uuid4().hex[:8]
    alice = f"alice_{tag}@example.com"
    bob = f"bob_{tag}@example.com"
    group = f"group_eng_{tag}"
    now = datetime.now(timezone.utc)

    cc_public = make_cc_pair(db_session, source=DocumentSource.WEB)
    cc_sync = make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE)
    cc_sync.access_type = AccessType.SYNC
    db_session.flush()

    node = HierarchyNode(
        raw_node_id=f"pgtool_node_{tag}",
        display_name=f"Tool Folder {tag}",
        source=DocumentSource.WEB,
        node_type=HierarchyNodeType.FOLDER,
        is_public=True,
    )
    db_session.add(node)
    db_session.flush()

    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_recent_{tag}",
        f"Report Alpha {tag}",
        primary_owners=[alice],
        doc_updated_at=now - timedelta(days=1),
        parent_hierarchy_node_id=node.id,
    )
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_old_{tag}",
        f"Report Beta {tag}",
        primary_owners=[bob],
        doc_updated_at=now - timedelta(days=400),
    )
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_nodate_{tag}",
        f"Report Gamma {tag}",
        primary_owners=[alice, bob],
    )
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_hidden_{tag}",
        f"Report Hidden {tag}",
        hidden=True,
    )
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_weird_{tag}",
        f"Progress 100%_done {tag}",
    )
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_pub_trap_{tag}",
        f"Progress 100xydone {tag}",
    )
    _make_doc(
        db_session,
        cc_sync,
        f"pgtool_sync_email_{tag}",
        f"Drive Email {tag}",
        external_user_emails=[alice],
    )
    _make_doc(
        db_session,
        cc_sync,
        f"pgtool_sync_group_{tag}",
        f"Drive Group {tag}",
        external_user_group_ids=[group],
    )
    _make_doc(
        db_session,
        cc_sync,
        f"pgtool_sync_private_{tag}",
        f"Drive Private {tag}",
    )
    _make_doc(
        db_session,
        cc_sync,
        f"pgtool_sync_publicflag_{tag}",
        f"Drive PublicFlag {tag}",
        is_public=True,
    )
    # Linked to BOTH cc_pairs — the dedup case.
    _make_doc(
        db_session,
        cc_public,
        f"pgtool_shared_{tag}",
        f"Shared Doc {tag}",
        doc_updated_at=now - timedelta(days=2),
    )
    _link_doc(db_session, cc_sync, f"pgtool_shared_{tag}")
    db_session.commit()

    yield DocEnv(
        tag=tag,
        alice=alice,
        group=group,
        cc_public=cc_public,
        cc_sync=cc_sync,
        node=node,
    )

    # A failed statement leaves the session's transaction aborted.
    db_session.rollback()
    cleanup_cc_pair(db_session, cc_public)
    cleanup_cc_pair(db_session, cc_sync)
    db_session.delete(node)
    db_session.commit()


def test_document_acl_scoping(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    public_visible = {
        f"Report Alpha {tag}",
        f"Report Beta {tag}",
        f"Report Gamma {tag}",
        f"Progress 100%_done {tag}",
        f"Progress 100xydone {tag}",
        f"Shared Doc {tag}",
        f"Drive PublicFlag {tag}",
    }

    anon = query_documents_for_tool(
        db_session, None, [], title_contains=tag, limit=100
    ).rows
    assert _sids(anon) == public_visible

    alice_docs = query_documents_for_tool(
        db_session, doc_env.alice, [], title_contains=tag, limit=100
    ).rows
    assert _sids(alice_docs) == public_visible | {f"Drive Email {tag}"}

    group_docs = query_documents_for_tool(
        db_session, None, [doc_env.group], title_contains=tag, limit=100
    ).rows
    assert _sids(group_docs) == public_visible | {f"Drive Group {tag}"}


def test_hidden_documents_excluded(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=f"Report Hidden {tag}", limit=100
    ).rows
    assert rows == []
    assert (
        count_documents_for_tool(
            db_session, None, [], title_contains=f"Report Hidden {tag}"
        )
        == 0
    )


def test_multi_cc_pair_doc_counted_once(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=f"Shared Doc {tag}", limit=100
    ).rows
    # Anonymous access comes only through the public WEB cc_pair.
    assert [source for _, source in rows] == [DocumentSource.WEB]
    assert (
        count_documents_for_tool(
            db_session, None, [], title_contains=f"Shared Doc {tag}"
        )
        == 1
    )


def test_doc_granted_by_two_sources_takes_one_row(
    db_session: Session, doc_env: DocEnv
) -> None:
    tag = doc_env.tag
    now = datetime.now(timezone.utc)
    # Public on the document, so the WEB row and the SYNC GOOGLE_DRIVE row
    # both grant access.
    _make_doc(
        db_session,
        doc_env.cc_public,
        f"pgtool_dual_new_{tag}",
        f"Dual {tag} New",
        is_public=True,
        doc_updated_at=now - timedelta(days=1),
    )
    _link_doc(db_session, doc_env.cc_sync, f"pgtool_dual_new_{tag}")
    _make_doc(
        db_session,
        doc_env.cc_public,
        f"pgtool_dual_old_{tag}",
        f"Dual {tag} Old",
        doc_updated_at=now - timedelta(days=5),
    )
    db_session.commit()

    rows = query_documents_for_tool(
        db_session, None, [], title_contains=f"Dual {tag}", limit=2
    ).rows
    assert [d.semantic_id for d, _ in rows] == [f"Dual {tag} New", f"Dual {tag} Old"]


def test_count_matches_row_mode(db_session: Session, doc_env: DocEnv) -> None:
    rows = query_documents_for_tool(
        db_session,
        doc_env.alice,
        [doc_env.group],
        title_contains=doc_env.tag,
        limit=100,
    ).rows
    count = count_documents_for_tool(
        db_session, doc_env.alice, [doc_env.group], title_contains=doc_env.tag
    )
    assert count == len(rows) == 9


def test_group_by_source(db_session: Session, doc_env: DocEnv) -> None:
    groups = count_documents_grouped_for_tool(
        db_session,
        doc_env.alice,
        [doc_env.group],
        DocumentGroupBy.SOURCE,
        title_contains=doc_env.tag,
    )
    # The shared doc is linked to both cc_pairs, but only its WEB (PUBLIC
    # connector) row grants access — source attribution follows the row that
    # passes the ACL, so it counts under web and not google_drive.
    assert {g.group: g.count for g in groups} == {
        DocumentSource.WEB.value: 6,
        DocumentSource.GOOGLE_DRIVE.value: 3,
    }


def test_group_by_owner(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    groups = count_documents_grouped_for_tool(
        db_session,
        doc_env.alice,
        [doc_env.group],
        DocumentGroupBy.OWNER,
        title_contains=tag,
    )
    # The multi-owner doc (Report Gamma) counts once per owner; ownerless docs
    # are absent from the grouping entirely.
    assert {g.group: g.count for g in groups} == {
        doc_env.alice: 2,
        f"bob_{tag}@example.com": 2,
    }


def test_like_wildcards_treated_literally(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    # Unescaped, "%"/"_" would also match "100xydone"; escaped, only the
    # literal "100%_done" title qualifies.
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=f"100%_done {tag}", limit=100
    ).rows
    assert _sids(rows) == {f"Progress 100%_done {tag}"}

    both = query_documents_for_tool(
        db_session, None, [], title_contains=f"done {tag}", limit=100
    ).rows
    assert _sids(both) == {
        f"Progress 100%_done {tag}",
        f"Progress 100xydone {tag}",
    }


def test_date_filters_use_source_updated_at(
    db_session: Session, doc_env: DocEnv
) -> None:
    tag = doc_env.tag
    now = datetime.now(timezone.utc)

    recent = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_after=now - timedelta(days=30),
        limit=100,
    ).rows
    # Docs with NULL doc_updated_at fall out of any date range.
    assert _sids(recent) == {f"Report Alpha {tag}", f"Shared Doc {tag}"}

    old = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_before=now - timedelta(days=100),
        limit=100,
    ).rows
    assert _sids(old) == {f"Report Beta {tag}"}

    beta = db_session.get(DbDocument, f"pgtool_pub_old_{tag}")
    assert beta is not None and beta.doc_updated_at is not None
    # Half-open range: a doc exactly on the bound falls in the later range only.
    before_bound = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_before=beta.doc_updated_at,
        limit=100,
    ).rows
    from_bound = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_after=beta.doc_updated_at,
        limit=100,
    ).rows
    assert f"Report Beta {tag}" not in _sids(before_bound)
    assert f"Report Beta {tag}" in _sids(from_bound)


def test_owned_by_filter(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=tag, owned_by=doc_env.alice, limit=100
    ).rows
    assert _sids(rows) == {f"Report Alpha {tag}", f"Report Gamma {tag}"}


def test_source_type_filter(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session,
        doc_env.alice,
        [doc_env.group],
        title_contains=tag,
        source_type=DocumentSource.GOOGLE_DRIVE,
        limit=100,
    ).rows
    # The shared doc is excluded: its google_drive cc_pair row (SYNC, no doc
    # perms) doesn't grant access — access comes via its WEB row only.
    assert _sids(rows) == {
        f"Drive Email {tag}",
        f"Drive Group {tag}",
        f"Drive PublicFlag {tag}",
    }


def test_parent_hierarchy_node_filter(db_session: Session, doc_env: DocEnv) -> None:
    rows = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=doc_env.tag,
        parent_hierarchy_node_id=doc_env.node.id,
        limit=100,
    ).rows
    assert _sids(rows) == {f"Report Alpha {doc_env.tag}"}


def test_ordering_and_limit(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=tag, limit=3
    ).rows
    # Newest first by doc_updated_at, NULL timestamps last.
    assert [d.semantic_id for d, _ in rows] == [
        f"Report Alpha {tag}",
        f"Shared Doc {tag}",
        f"Report Beta {tag}",
    ]

    clamped = query_documents_for_tool(
        db_session, None, [], title_contains=tag, limit=0
    ).rows
    assert len(clamped) == 1


# ============================== Paging ==============================


@dataclass
class PagingEnv:
    tag: str
    cc_pair: ConnectorCredentialPair
    doc_ids: set[str]


@pytest.fixture()
def paging_env(db_session: Session) -> Generator[PagingEnv, None, None]:
    """101 public documents: 40 share one timestamp, 40 have distinct
    timestamps and 21 have none, so pages cross ties and the NULL boundary."""
    tag = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    cc_pair = make_cc_pair(db_session, source=DocumentSource.WEB)
    doc_ids: set[str] = set()
    for i in range(101):
        if i < 40:
            updated_at: datetime | None = now - timedelta(days=1)
        elif i < 80:
            updated_at = now - timedelta(days=2, minutes=i)
        else:
            updated_at = None
        doc_id = f"pgtool_page_{tag}_{i:03d}"
        _make_doc(
            db_session,
            cc_pair,
            doc_id,
            f"Paged {tag} {i:03d}",
            doc_updated_at=updated_at,
        )
        doc_ids.add(doc_id)
    db_session.commit()

    yield PagingEnv(tag=tag, cc_pair=cc_pair, doc_ids=doc_ids)

    # A failed statement leaves the session's transaction aborted.
    db_session.rollback()
    cleanup_cc_pair(db_session, cc_pair)
    db_session.commit()


def _walk_pages(db_session: Session, title: str, page_size: int) -> list[list[str]]:
    pages: list[list[str]] = []
    after = None
    while True:
        page = query_documents_for_tool(
            db_session, None, [], title_contains=title, after=after, limit=page_size
        )
        pages.append([doc.id for doc, _ in page.rows])
        if page.next_cursor is None:
            return pages
        after = page.next_cursor


def test_paging_returns_every_document_once_in_order(
    db_session: Session, paging_env: PagingEnv
) -> None:
    title = f"Paged {paging_env.tag}"
    pages = _walk_pages(db_session, title, page_size=7)
    walked = [doc_id for page in pages for doc_id in page]
    assert len(walked) == 101
    assert set(walked) == paging_env.doc_ids
    assert [len(page) for page in pages] == [7] * 14 + [3]

    # The pages follow the single-listing order.
    in_one_listing = _walk_pages(db_session, title, page_size=100)
    assert walked == [doc_id for page in in_one_listing for doc_id in page]


def test_paging_reads_timestamps_from_the_statement(
    db_session: Session, paging_env: PagingEnv
) -> None:
    """The session holds every paged document, then their timestamps change
    without the session seeing it. The cursor must use the current values."""
    title = f"Paged {paging_env.tag}"
    # The session holds loaded objects only while something references them.
    held = (
        db_session.query(DbDocument).filter(DbDocument.id.in_(paging_env.doc_ids)).all()
    )
    db_session.execute(
        update(DbDocument)
        .where(DbDocument.id.in_(paging_env.doc_ids))
        .where(DbDocument.doc_updated_at.is_not(None))
        .values(doc_updated_at=DbDocument.doc_updated_at + timedelta(hours=12))
        .execution_options(synchronize_session=False)
    )
    walked = [
        doc_id
        for page in _walk_pages(db_session, title, page_size=7)
        for doc_id in page
    ]
    assert all(doc in db_session for doc in held)
    db_session.rollback()
    assert len(walked) == 101
    assert set(walked) == paging_env.doc_ids


def test_page_size_is_capped_at_100(db_session: Session, paging_env: PagingEnv) -> None:
    pages = _walk_pages(db_session, f"Paged {paging_env.tag}", page_size=500)
    assert [len(page) for page in pages] == [100, 1]


def test_documents_indexed_between_pages_do_not_shift_them(
    db_session: Session, paging_env: PagingEnv
) -> None:
    title = f"Paged {paging_env.tag}"
    first = query_documents_for_tool(
        db_session, None, [], title_contains=title, limit=50
    )
    assert first.next_cursor is not None
    # A new newest document sorts before the cursor, so later pages skip it
    # and still return every other document once.
    _make_doc(
        db_session,
        paging_env.cc_pair,
        f"pgtool_page_{paging_env.tag}_new",
        f"Paged {paging_env.tag} new",
        doc_updated_at=datetime.now(timezone.utc),
    )
    db_session.commit()
    rest: list[str] = []
    after = first.next_cursor
    while after is not None:
        page = query_documents_for_tool(
            db_session, None, [], title_contains=title, after=after, limit=50
        )
        rest.extend(doc.id for doc, _ in page.rows)
        after = page.next_cursor
    walked = [doc.id for doc, _ in first.rows] + rest
    assert len(walked) == 101
    assert set(walked) == paging_env.doc_ids


# =========================== Knowledge scope ===========================


@dataclass
class ScopeEnv:
    doc_env: DocEnv
    child_folder: HierarchyNode  # under doc_env.node, holds "Nested"
    page_node: HierarchyNode  # a node that is the "Report Beta" document
    # A Confluence page whose node came after its document was indexed, so its
    # document_id is NULL and raw_node_id is the document id ("Progress 100%_done").
    late_page_node: HierarchyNode
    document_set: DocumentSet  # on the SYNC Drive cc_pair


@pytest.fixture()
def scope_env(db_session: Session, doc_env: DocEnv) -> Generator[ScopeEnv, None, None]:
    tag = doc_env.tag
    now = datetime.now(timezone.utc)
    child_folder = HierarchyNode(
        raw_node_id=f"pgtool_child_{tag}",
        display_name=f"Child Folder {tag}",
        source=DocumentSource.WEB,
        node_type=HierarchyNodeType.FOLDER,
        is_public=True,
        parent_id=doc_env.node.id,
    )
    page_node = HierarchyNode(
        raw_node_id=f"pgtool_page_{tag}",
        display_name=f"Page {tag}",
        source=DocumentSource.WEB,
        node_type=HierarchyNodeType.PAGE,
        is_public=True,
        document_id=f"pgtool_pub_old_{tag}",
    )
    late_page_node = HierarchyNode(
        raw_node_id=f"pgtool_pub_weird_{tag}",
        display_name=f"Late Page {tag}",
        source=DocumentSource.CONFLUENCE,
        node_type=HierarchyNodeType.PAGE,
        is_public=True,
    )
    db_session.add_all([child_folder, page_node, late_page_node])
    db_session.flush()
    _make_doc(
        db_session,
        doc_env.cc_public,
        f"pgtool_nested_{tag}",
        f"Nested {tag}",
        doc_updated_at=now - timedelta(days=3),
        doc_created_at=now - timedelta(days=3),
        parent_hierarchy_node_id=child_folder.id,
    )
    document_set = DocumentSet(name=f"pgtool_set_{tag}", is_up_to_date=True)
    db_session.add(document_set)
    db_session.flush()
    db_session.add(
        DocumentSet__ConnectorCredentialPair(
            document_set_id=document_set.id,
            connector_credential_pair_id=doc_env.cc_sync.id,
            is_current=True,
        )
    )
    tag_row = TagRow(
        tag_key=f"team_{tag}", tag_value="infra", source=DocumentSource.WEB
    )
    db_session.add(tag_row)
    db_session.flush()
    db_session.add(
        Document__Tag(document_id=f"pgtool_pub_nodate_{tag}", tag_id=tag_row.id)
    )
    db_session.commit()

    yield ScopeEnv(
        doc_env=doc_env,
        child_folder=child_folder,
        page_node=page_node,
        late_page_node=late_page_node,
        document_set=document_set,
    )

    # A failed statement leaves the session's transaction aborted.
    db_session.rollback()
    # Rows that reference the doc_env documents and folder go first.
    db_session.query(Document__Tag).filter(Document__Tag.tag_id == tag_row.id).delete()
    db_session.delete(tag_row)
    db_session.query(DocumentSet__ConnectorCredentialPair).filter(
        DocumentSet__ConnectorCredentialPair.document_set_id == document_set.id
    ).delete()
    db_session.delete(document_set)
    db_session.delete(page_node)
    db_session.delete(late_page_node)
    db_session.query(DocumentByConnectorCredentialPair).filter(
        DocumentByConnectorCredentialPair.id == f"pgtool_nested_{tag}"
    ).delete()
    db_session.query(DbDocument).filter(
        DbDocument.id == f"pgtool_nested_{tag}"
    ).delete()
    db_session.delete(child_folder)
    db_session.commit()


def _scoped_titles(db_session: Session, tag: str, scope: DocumentScope) -> set[str]:
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=tag, limit=100, scope=scope
    ).rows
    count = count_documents_for_tool(
        db_session, None, [], title_contains=tag, scope=scope
    )
    assert count == len(rows)
    return {d.semantic_id for d, _ in rows}


def test_scope_knowledge_elements(db_session: Session, scope_env: ScopeEnv) -> None:
    tag = scope_env.doc_env.tag
    node = scope_env.doc_env.node

    attached = DocumentScope(attached_document_ids=[f"pgtool_pub_old_{tag}"])
    assert _scoped_titles(db_session, tag, attached) == {f"Report Beta {tag}"}

    # Any of a document's cc_pairs puts it in a set: the shared doc is in
    # through its Drive row, although anonymous access comes from its WEB row.
    doc_set = DocumentScope(document_set_names=[scope_env.document_set.name])
    assert _scoped_titles(db_session, tag, doc_set) == {
        f"Drive PublicFlag {tag}",
        f"Shared Doc {tag}",
    }

    # A folder covers its whole subtree.
    folder = DocumentScope(hierarchy_node_ids=[node.id])
    assert _scoped_titles(db_session, tag, folder) == {
        f"Report Alpha {tag}",
        f"Nested {tag}",
    }

    # A node that is a document includes that document.
    page = DocumentScope(hierarchy_node_ids=[scope_env.page_node.id])
    assert _scoped_titles(db_session, tag, page) == {f"Report Beta {tag}"}

    late = DocumentScope(hierarchy_node_ids=[scope_env.late_page_node.id])
    assert _scoped_titles(db_session, tag, late) == {f"Progress 100%_done {tag}"}

    # Knowledge elements are ORed.
    either = DocumentScope(
        attached_document_ids=[f"pgtool_pub_old_{tag}"], hierarchy_node_ids=[node.id]
    )
    assert _scoped_titles(db_session, tag, either) == {
        f"Report Alpha {tag}",
        f"Nested {tag}",
        f"Report Beta {tag}",
    }


def test_scope_request_filters(db_session: Session, scope_env: ScopeEnv) -> None:
    tag = scope_env.doc_env.tag
    now = datetime.now(timezone.utc)

    # Undated documents follow the search filter. A recent start drops them
    # with the older documents; an old, open-ended start keeps them.
    recent = DocumentScope(updated_at_range=TimeRange(start=now - timedelta(days=30)))
    assert _scoped_titles(db_session, tag, recent) == {
        f"Report Alpha {tag}",
        f"Shared Doc {tag}",
        f"Nested {tag}",
    }
    undated = {
        f"Report Gamma {tag}",
        f"Progress 100%_done {tag}",
        f"Progress 100xydone {tag}",
        f"Drive PublicFlag {tag}",
    }
    old_open = DocumentScope(
        updated_at_range=TimeRange(start=now - timedelta(days=200))
    )
    assert _scoped_titles(db_session, tag, old_open) == undated | {
        f"Report Alpha {tag}",
        f"Shared Doc {tag}",
        f"Nested {tag}",
    }
    old_closed = DocumentScope(
        updated_at_range=TimeRange(
            start=now - timedelta(days=200), end=now - timedelta(hours=36)
        )
    )
    assert _scoped_titles(db_session, tag, old_closed) == {
        f"Shared Doc {tag}",
        f"Nested {tag}",
    }

    # A created range keeps every undated document; only "Nested" has a
    # creation time, and it is before the range.
    created = DocumentScope(created_at_range=TimeRange(start=now - timedelta(days=1)))
    assert _scoped_titles(db_session, tag, created) == undated | {
        f"Report Alpha {tag}",
        f"Report Beta {tag}",
        f"Shared Doc {tag}",
    }

    tagged = DocumentScope(tags=[Tag(tag_key=f"team_{tag}", tag_value="infra")])
    assert _scoped_titles(db_session, tag, tagged) == {f"Report Gamma {tag}"}

    # Request filters are ANDed with the knowledge.
    narrowed = DocumentScope(
        hierarchy_node_ids=[scope_env.doc_env.node.id],
        source_types=[DocumentSource.WEB],
        updated_at_range=TimeRange(start=now - timedelta(days=2)),
    )
    assert _scoped_titles(db_session, tag, narrowed) == {f"Report Alpha {tag}"}

    drive_only = DocumentScope(source_types=[DocumentSource.GOOGLE_DRIVE])
    assert _scoped_titles(db_session, tag, drive_only) == {f"Drive PublicFlag {tag}"}
    assert _scoped_titles(db_session, tag, DocumentScope(source_types=[])) == set()

    # Uploaded files are not documents, so a files-only knowledge matches none.
    files_only = DocumentScope(includes_user_files=True)
    assert _scoped_titles(db_session, tag, files_only) == set()

    groups = count_documents_grouped_for_tool(
        db_session,
        None,
        [],
        DocumentGroupBy.SOURCE,
        title_contains=tag,
        scope=DocumentScope(hierarchy_node_ids=[scope_env.doc_env.node.id]),
    )
    assert {g.group: g.count for g in groups} == {DocumentSource.WEB.value: 2}


def test_scope_folder_listing(db_session: Session, scope_env: ScopeEnv) -> None:
    tag = scope_env.doc_env.tag
    node = scope_env.doc_env.node

    def names(scope: DocumentScope) -> set[str]:
        nodes = query_hierarchy_nodes_for_tool(
            db_session, None, [], name_contains=tag, limit=100, scope=scope
        )
        count = count_hierarchy_nodes_for_tool(
            db_session, None, [], name_contains=tag, scope=scope
        )
        assert count == len(nodes)
        return {n.display_name for n in nodes}

    assert names(DocumentScope()) == {
        f"Tool Folder {tag}",
        f"Child Folder {tag}",
        f"Page {tag}",
        f"Late Page {tag}",
    }
    assert names(DocumentScope(hierarchy_node_ids=[node.id])) == {
        f"Tool Folder {tag}",
        f"Child Folder {tag}",
    }
    # Folders that hold a document in the knowledge.
    nested = DocumentScope(attached_document_ids=[f"pgtool_nested_{tag}"])
    assert names(nested) == {f"Child Folder {tag}"}
    assert names(DocumentScope(includes_user_files=True)) == set()


# ============================ HierarchyNode ============================


def _node(
    tag: str,
    raw_suffix: str,
    display_name: str,
    *,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
    node_type: HierarchyNodeType = HierarchyNodeType.FOLDER,
    is_public: bool = True,
    external_user_emails: list[str] | None = None,
    parent_id: int | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=f"pgtool_{raw_suffix}_{tag}",
        display_name=display_name,
        source=source,
        node_type=node_type,
        is_public=is_public,
        external_user_emails=external_user_emails,
        parent_id=parent_id,
    )


@dataclass
class NodeEnv:
    tag: str
    alice: str
    root: HierarchyNode
    nodes: list[HierarchyNode]


@pytest.fixture()
def node_env(db_session: Session) -> Generator[NodeEnv, None, None]:
    tag = uuid4().hex[:8]
    alice = f"alice_{tag}@example.com"

    root = _node(tag, "root", f"AAA Folder {tag}")
    db_session.add(root)
    db_session.flush()

    others = [
        _node(tag, "child", f"BBB Child {tag}", parent_id=root.id),
        _node(
            tag,
            "drive",
            f"CCC Drive {tag}",
            node_type=HierarchyNodeType.SHARED_DRIVE,
            parent_id=root.id,
        ),
        _node(tag, "private", f"DDD Private {tag}", is_public=False),
        _node(
            tag,
            "email",
            f"EEE Email {tag}",
            is_public=False,
            external_user_emails=[alice],
        ),
        _node(
            tag,
            "confluence",
            f"FFF Confluence {tag}",
            source=DocumentSource.CONFLUENCE,
        ),
        # STUB — must never be surfaced, even though its name matches.
        _node(tag, "stub", f"GGG Stub {tag}", node_type=HierarchyNodeType.STUB),
    ]
    for n in others:
        db_session.add(n)
    db_session.commit()

    yield NodeEnv(tag=tag, alice=alice, root=root, nodes=[root, *others])

    # A failed statement leaves the session's transaction aborted.
    db_session.rollback()
    # Children first — the parent FK is SET NULL, but this keeps the ORM flush simple.
    for n in [*others, root]:
        db_session.delete(n)
    db_session.commit()


def test_hierarchy_mit_filter_returns_all_non_stub(
    db_session: Session, node_env: NodeEnv
) -> None:
    rows = _query_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=node_env.tag,
        limit=100,
    )
    names = {n.display_name for n in rows}
    tag = node_env.tag
    assert names == {
        f"AAA Folder {tag}",
        f"BBB Child {tag}",
        f"CCC Drive {tag}",
        f"DDD Private {tag}",
        f"EEE Email {tag}",
        f"FFF Confluence {tag}",
    }


def test_hierarchy_ee_filter_applies_acl(
    db_session: Session, node_env: NodeEnv
) -> None:
    tag = node_env.tag
    rows = _query_hierarchy_nodes(
        db_session,
        ee_hierarchy_filter(db_session, node_env.alice, [], None),
        name_contains=tag,
        limit=100,
    )
    names = {n.display_name for n in rows}
    assert names == {
        f"AAA Folder {tag}",
        f"BBB Child {tag}",
        f"CCC Drive {tag}",
        f"EEE Email {tag}",
        f"FFF Confluence {tag}",
    }

    no_access = _query_hierarchy_nodes(
        db_session,
        ee_hierarchy_filter(db_session, None, [], None),
        name_contains=tag,
        limit=100,
    )
    assert {n.display_name for n in no_access} == {
        f"AAA Folder {tag}",
        f"BBB Child {tag}",
        f"CCC Drive {tag}",
        f"FFF Confluence {tag}",
    }


def test_hierarchy_parent_and_type_filters(
    db_session: Session, node_env: NodeEnv
) -> None:
    tag = node_env.tag
    children = _query_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=tag,
        parent_id=node_env.root.id,
        limit=100,
    )
    assert {n.display_name for n in children} == {
        f"BBB Child {tag}",
        f"CCC Drive {tag}",
    }

    drives = _query_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=tag,
        node_type=HierarchyNodeType.SHARED_DRIVE,
        limit=100,
    )
    assert {n.display_name for n in drives} == {f"CCC Drive {tag}"}

    confluence = _query_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=tag,
        source_type=DocumentSource.CONFLUENCE,
        limit=100,
    )
    assert {n.display_name for n in confluence} == {f"FFF Confluence {tag}"}


def test_hierarchy_count_and_ordering(db_session: Session, node_env: NodeEnv) -> None:
    rows = _query_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=node_env.tag,
        limit=100,
    )
    count = _count_hierarchy_nodes(
        db_session,
        mit_hierarchy_filter(db_session, None, [], None),
        name_contains=node_env.tag,
    )
    assert count == len(rows) == 6
    # Ordered by display_name; the fixture names are alphabetized by prefix.
    assert [n.display_name for n in rows] == sorted(n.display_name for n in rows)


def test_hierarchy_public_dispatchers(db_session: Session, node_env: NodeEnv) -> None:
    """Edition-agnostic invariants for the versioned public entry points:
    public nodes always visible, STUBs never, count matches rows."""
    tag = node_env.tag
    rows = query_hierarchy_nodes_for_tool(
        db_session, node_env.alice, [], name_contains=tag, limit=100
    )
    names = {n.display_name for n in rows}
    assert f"AAA Folder {tag}" in names
    assert f"GGG Stub {tag}" not in names

    count = count_hierarchy_nodes_for_tool(
        db_session, node_env.alice, [], name_contains=tag
    )
    assert count == len(rows)
