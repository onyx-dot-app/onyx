"""build_cc_pair_hierarchy_breakdown counts a cc-pair's documents per
hierarchy node, and the Confluence config names the nodes it expects.
Every test rolls back."""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    HierarchyNodeType,
    IndexingStatus,
    IndexModelStatus,
)
from onyx.db.hierarchy import (
    ensure_source_node_exists,
    upsert_hierarchy_node_cc_pair_entries,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    Document,
    DocumentByConnectorCredentialPair,
    HierarchyNode,
    IndexAttempt,
    SearchSettings,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.hierarchy_breakdown import build_cc_pair_hierarchy_breakdown
from onyx.server.documents.models import HierarchyBreakdownEntry


@pytest.fixture()
def session(db_session: Session) -> Generator[Session, None, None]:
    yield db_session
    db_session.rollback()


def _cc_pair(
    db_session: Session,
    source: DocumentSource,
    config: dict[str, Any],
    *,
    indexed: bool = True,
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"breakdown {uuid4().hex[:8]}",
        source=source,
        input_type=InputType.LOAD_STATE,
        connector_specific_config=config,
    )
    credential = Credential(source=source, credential_json={}, admin_public=True)
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
    db_session.flush()
    if indexed:
        _successful_attempt(
            db_session, cc_pair, get_current_search_settings(db_session).id
        )
    return cc_pair


def _successful_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings_id: int,
    *,
    is_synthetic_seed: bool = False,
) -> None:
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            search_settings_id=search_settings_id,
            from_beginning=False,
            status=IndexingStatus.SUCCESS,
            is_synthetic_seed=is_synthetic_seed,
        )
    )
    db_session.flush()


def _node(
    db_session: Session,
    source: DocumentSource,
    raw_node_id: str,
    node_type: HierarchyNodeType,
    parent: HierarchyNode,
    owners: list[ConnectorCredentialPair],
    display_name: str | None = None,
) -> HierarchyNode:
    node = HierarchyNode(
        raw_node_id=raw_node_id,
        display_name=display_name or raw_node_id,
        source=source,
        node_type=node_type,
        parent_id=parent.id,
    )
    db_session.add(node)
    db_session.flush()
    for owner in owners:
        upsert_hierarchy_node_cc_pair_entries(
            db_session, [node.id], owner.connector_id, owner.credential_id, commit=False
        )
    return node


def _doc(
    db_session: Session,
    parent: HierarchyNode | None,
    cc_pair: ConnectorCredentialPair,
    *,
    document_id: str | None = None,
    has_been_indexed: bool = True,
) -> str:
    document_id = document_id or f"breakdown_doc_{uuid4().hex}"
    db_session.add(
        Document(
            id=document_id,
            semantic_id=document_id,
            parent_hierarchy_node_id=parent.id if parent else None,
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=document_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=has_been_indexed,
        )
    )
    db_session.flush()
    return document_id


def _counts(entries: list[HierarchyBreakdownEntry]) -> dict[str, int | None]:
    return {entry.raw_node_id: entry.doc_count for entry in entries}


def test_top_level_nodes_count_their_subtree(session: Session) -> None:
    source = DocumentSource.NOTION
    tag = uuid4().hex[:8]
    pair = _cc_pair(session, source, {})
    other_pair = _cc_pair(session, source, {})
    root = ensure_source_node_exists(session, source, commit=False)

    workspace_a = _node(
        session, source, f"a_{tag}", HierarchyNodeType.WORKSPACE, root, [pair]
    )
    page_a1 = _node(
        session, source, f"a1_{tag}", HierarchyNodeType.PAGE, workspace_a, [pair]
    )
    folder_a1a = _node(
        session, source, f"a1a_{tag}", HierarchyNodeType.FOLDER, page_a1, [pair]
    )
    database_b = _node(
        session, source, f"b_{tag}", HierarchyNodeType.DATABASE, root, [pair]
    )
    # Only the other pair has this node, so it is not listed.
    _node(session, source, f"c_{tag}", HierarchyNodeType.WORKSPACE, root, [other_pair])
    stub = _node(session, source, f"stub_{tag}", HierarchyNodeType.STUB, root, [pair])

    _doc(session, workspace_a, pair)
    _doc(session, page_a1, pair)
    _doc(session, folder_a1a, pair)
    _doc(session, database_b, pair)
    # Page a1 is also a document: its node points to it and its parent is a.
    # Both rules match it, and it counts once.
    page_a1.document_id = _doc(session, workspace_a, pair)
    session.flush()
    # Not counted: a document of another pair, and one not indexed yet.
    _doc(session, workspace_a, other_pair)
    _doc(session, folder_a1a, pair, has_been_indexed=False)
    # In no listed node: no hierarchy parent, and under a STUB node.
    _doc(session, None, pair)
    _doc(session, stub, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert set(breakdown.nodes_by_type) == {
        HierarchyNodeType.WORKSPACE,
        HierarchyNodeType.DATABASE,
    }
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.WORKSPACE]) == {
        f"a_{tag}": 4
    }
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.DATABASE]) == {
        f"b_{tag}": 1
    }
    assert breakdown.other_doc_count == 2


def test_no_successful_attempt_has_no_breakdown(session: Session) -> None:
    source = DocumentSource.NOTION
    pair = _cc_pair(session, source, {}, indexed=False)
    root = ensure_source_node_exists(session, source, commit=False)
    node = _node(
        session,
        source,
        f"a_{uuid4().hex[:8]}",
        HierarchyNodeType.WORKSPACE,
        root,
        [pair],
    )
    _doc(session, node, pair)

    assert build_cc_pair_hierarchy_breakdown(session, pair) is None
    # The reindex port's seed is not an index run.
    _successful_attempt(
        session, pair, get_current_search_settings(session).id, is_synthetic_seed=True
    )
    assert build_cc_pair_hierarchy_breakdown(session, pair) is None


def test_success_under_past_search_settings_counts(session: Session) -> None:
    """An embedding swap moves the earlier runs to past search settings, but
    the documents stay."""
    source = DocumentSource.NOTION
    pair = _cc_pair(session, source, {}, indexed=False)
    current_row = (
        session.execute(
            select(SearchSettings.__table__).where(
                SearchSettings.id == get_current_search_settings(session).id
            )
        )
        .mappings()
        .one()
    )
    past_id = session.execute(
        insert(SearchSettings)
        .values(
            {
                **{key: value for key, value in current_row.items() if key != "id"},
                "status": IndexModelStatus.PAST.value,
            }
        )
        .returning(SearchSettings.id)
    ).scalar_one()
    _successful_attempt(session, pair, past_id)
    root = ensure_source_node_exists(session, source, commit=False)
    node = _node(
        session,
        source,
        f"a_{uuid4().hex[:8]}",
        HierarchyNodeType.WORKSPACE,
        root,
        [pair],
    )
    _doc(session, node, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.WORKSPACE]) == {
        node.raw_node_id: 1
    }


_CONFLUENCE_BASE = {"wiki_base": "https://example.atlassian.net", "is_cloud": True}


def _page_url(tag: str, space_key: str, page_id: str) -> str:
    return f"https://{tag}.atlassian.net/wiki/spaces/{space_key}/pages/{page_id}/Title"


def test_confluence_space_mode_shows_the_configured_space(session: Session) -> None:
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    eng, prod = f"ENG{tag}", f"PROD{tag}"
    pair = _cc_pair(
        session,
        source,
        # The page id belongs to an unused tab of the form, so it names nothing.
        _CONFLUENCE_BASE | {"space": prod, "page_id": ""},
    )
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(
        session, source, eng, HierarchyNodeType.SPACE, root, [pair], "Engineering"
    )
    page = _node(
        session,
        source,
        _page_url(tag, eng, "233056"),
        HierarchyNodeType.PAGE,
        space,
        [pair],
    )
    _doc(session, space, pair)
    _doc(session, page, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    # Pages show only when the config names one.
    assert list(breakdown.nodes_by_type) == [HierarchyNodeType.SPACE]
    assert breakdown.config_fields == ["space", "page_id"]
    spaces = breakdown.nodes_by_type[HierarchyNodeType.SPACE]
    assert [entry.model_dump() for entry in spaces] == [
        {
            "raw_node_id": eng,
            "display_name": "Engineering",
            "link": None,
            "doc_count": 2,
        },
        {"raw_node_id": prod, "display_name": None, "link": None, "doc_count": None},
    ]


def test_confluence_page_mode_shows_the_configured_page(session: Session) -> None:
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    eng = f"ENG{tag}"
    configured_page_id = "233056"
    pair = _cc_pair(
        session,
        source,
        _CONFLUENCE_BASE | {"page_id": configured_page_id, "index_recursively": True},
    )
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(session, source, eng, HierarchyNodeType.SPACE, root, [pair])
    configured_url = _page_url(tag, eng, configured_page_id)
    configured_page = _node(
        session,
        source,
        configured_url,
        HierarchyNodeType.PAGE,
        space,
        [pair],
        "Project Tracker",
    )
    child_page = _node(
        session,
        source,
        _page_url(tag, eng, "283019"),
        HierarchyNodeType.PAGE,
        configured_page,
        [pair],
    )
    # The configured page is a document too, and counts as one of its docs.
    configured_page.document_id = _doc(session, space, pair, document_id=configured_url)
    child_page.document_id = _doc(
        session, configured_page, pair, document_id=child_page.raw_node_id
    )
    _doc(session, None, pair)
    session.flush()

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.SPACE]) == {eng: 2}
    # The configured page is inside the listed space: its documents count in
    # both rows, but never in "other". Only the document without a parent does.
    assert breakdown.other_doc_count == 1
    # The child page is a PAGE node, but the config does not name it.
    pages = breakdown.nodes_by_type[HierarchyNodeType.PAGE]
    assert _counts(pages) == {configured_page_id: 2}
    assert pages[0].display_name == "Project Tracker"


def test_confluence_configured_page_without_documents_is_not_indexed(
    session: Session,
) -> None:
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    pair = _cc_pair(session, source, _CONFLUENCE_BASE | {"page_id": "283019"})
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(session, source, f"ENG{tag}", HierarchyNodeType.SPACE, root, [pair])
    # The page node exists, but no document of the pair is under it.
    _node(
        session,
        source,
        _page_url(tag, f"ENG{tag}", "283019"),
        HierarchyNodeType.PAGE,
        space,
        [pair],
        "Product Spec",
    )

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert [
        entry.model_dump() for entry in breakdown.nodes_by_type[HierarchyNodeType.PAGE]
    ] == [
        {
            "raw_node_id": "283019",
            "display_name": "Product Spec",
            "link": None,
            "doc_count": None,
        }
    ]
    # A space seen in the hierarchy, but not named by the config, shows 0.
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.SPACE]) == {f"ENG{tag}": 0}


def test_confluence_configured_space_matches_without_case(session: Session) -> None:
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    eng = f"ENG{tag}"
    # Confluence does not allow two space keys that differ only in case.
    pair = _cc_pair(session, source, _CONFLUENCE_BASE | {"space": f" {eng.lower()} "})
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(session, source, eng, HierarchyNodeType.SPACE, root, [pair])
    _doc(session, space, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.SPACE]) == {eng: 1}
    assert breakdown.other_doc_count == 0


def test_confluence_configured_leaf_page_shows_its_document(session: Session) -> None:
    """A page without child pages or attachments has no hierarchy node. Its
    document stands for it."""
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    eng = f"ENG{tag}"
    page_id = "233056"
    pair = _cc_pair(session, source, _CONFLUENCE_BASE | {"page_id": page_id})
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(session, source, eng, HierarchyNodeType.SPACE, root, [pair])
    page_url = _page_url(tag, eng, page_id)
    _doc(session, space, pair, document_id=page_url)
    # A page whose id only starts with the configured id does not match.
    _doc(session, space, pair, document_id=_page_url(tag, eng, f"{page_id}9"))
    _doc(session, None, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert [
        entry.model_dump() for entry in breakdown.nodes_by_type[HierarchyNodeType.PAGE]
    ] == [
        {
            "raw_node_id": page_id,
            "display_name": page_url,
            "link": None,
            "doc_count": 1,
        }
    ]
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.SPACE]) == {eng: 2}
    # Only the document without a parent is in "other".
    assert breakdown.other_doc_count == 1


def test_confluence_page_node_without_document_link_counts_its_page(
    session: Session,
) -> None:
    """A page that gains a child after it was indexed gets its node later. The
    indexing does not set the node's document_id then, so the raw id finds the
    page's document."""
    source = DocumentSource.CONFLUENCE
    tag = uuid4().hex[:8].upper()
    eng = f"ENG{tag}"
    page_id = "233056"
    pair = _cc_pair(session, source, _CONFLUENCE_BASE | {"page_id": page_id})
    root = ensure_source_node_exists(session, source, commit=False)
    space = _node(session, source, eng, HierarchyNodeType.SPACE, root, [pair])
    page_url = _page_url(tag, eng, page_id)
    _doc(session, space, pair, document_id=page_url)
    page = _node(session, source, page_url, HierarchyNodeType.PAGE, space, [pair])
    _doc(session, page, pair)

    breakdown = build_cc_pair_hierarchy_breakdown(session, pair)

    assert breakdown is not None
    assert page.document_id is None
    assert _counts(breakdown.nodes_by_type[HierarchyNodeType.PAGE]) == {page_id: 2}
    assert breakdown.other_doc_count == 0
