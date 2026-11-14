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
from sqlalchemy.orm import Session

from ee.onyx.db.postgres_tool import (
    _hierarchy_node_access_filter as ee_hierarchy_filter,
)
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType, HierarchyNodeType
from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentByConnectorCredentialPair,
    HierarchyNode,
)
from onyx.db.models import Document as DbDocument
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

    anon = query_documents_for_tool(db_session, None, [], title_contains=tag, limit=100)
    assert _sids(anon) == public_visible

    alice_docs = query_documents_for_tool(
        db_session, doc_env.alice, [], title_contains=tag, limit=100
    )
    assert _sids(alice_docs) == public_visible | {f"Drive Email {tag}"}

    group_docs = query_documents_for_tool(
        db_session, None, [doc_env.group], title_contains=tag, limit=100
    )
    assert _sids(group_docs) == public_visible | {f"Drive Group {tag}"}


def test_hidden_documents_excluded(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=f"Report Hidden {tag}", limit=100
    )
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
    )
    # Anonymous access comes only through the public WEB cc_pair.
    assert [source for _, source in rows] == [DocumentSource.WEB]
    assert (
        count_documents_for_tool(
            db_session, None, [], title_contains=f"Shared Doc {tag}"
        )
        == 1
    )


def test_count_matches_row_mode(db_session: Session, doc_env: DocEnv) -> None:
    rows = query_documents_for_tool(
        db_session,
        doc_env.alice,
        [doc_env.group],
        title_contains=doc_env.tag,
        limit=100,
    )
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
    )
    assert _sids(rows) == {f"Progress 100%_done {tag}"}

    both = query_documents_for_tool(
        db_session, None, [], title_contains=f"done {tag}", limit=100
    )
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
    )
    # Docs with NULL doc_updated_at fall out of any date range.
    assert _sids(recent) == {f"Report Alpha {tag}", f"Shared Doc {tag}"}

    old = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_before=now - timedelta(days=100),
        limit=100,
    )
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
    )
    from_bound = query_documents_for_tool(
        db_session,
        None,
        [],
        title_contains=tag,
        updated_after=beta.doc_updated_at,
        limit=100,
    )
    assert f"Report Beta {tag}" not in _sids(before_bound)
    assert f"Report Beta {tag}" in _sids(from_bound)


def test_owned_by_filter(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(
        db_session, None, [], title_contains=tag, owned_by=doc_env.alice, limit=100
    )
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
    )
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
    )
    assert _sids(rows) == {f"Report Alpha {doc_env.tag}"}


def test_ordering_and_limit(db_session: Session, doc_env: DocEnv) -> None:
    tag = doc_env.tag
    rows = query_documents_for_tool(db_session, None, [], title_contains=tag, limit=3)
    # Newest first by doc_updated_at, NULL timestamps last.
    assert [d.semantic_id for d, _ in rows] == [
        f"Report Alpha {tag}",
        f"Shared Doc {tag}",
        f"Report Beta {tag}",
    ]

    clamped = query_documents_for_tool(
        db_session, None, [], title_contains=tag, limit=0
    )
    assert len(clamped) == 1


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
