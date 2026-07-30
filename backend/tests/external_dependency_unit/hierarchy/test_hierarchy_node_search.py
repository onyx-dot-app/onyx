"""Tests for hierarchy node display_name search.

Covers case-insensitive substring matching, source filtering, exclusion of
STUB/SOURCE nodes, and ACL filtering in the EE version.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.hierarchy import _search_accessible_hierarchy_nodes as ee_search
from onyx.configs.constants import DocumentSource
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import _search_accessible_hierarchy_nodes as mit_search
from onyx.db.hierarchy import get_source_hierarchy_node
from onyx.db.models import HierarchyNode


def _node(
    raw_node_id: str,
    display_name: str,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
    node_type: HierarchyNodeType = HierarchyNodeType.FOLDER,
    *,
    is_public: bool = True,
    external_user_emails: list[str] | None = None,
    external_user_group_ids: list[str] | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=raw_node_id,
        display_name=display_name,
        source=source,
        node_type=node_type,
        is_public=is_public,
        external_user_emails=external_user_emails,
        external_user_group_ids=external_user_group_ids,
    )


@pytest.fixture()
def search_nodes(db_session: Session) -> Generator[list[HierarchyNode], None, None]:
    tag = uuid4().hex[:8]
    # Display names are deliberately simple so search substrings are unambiguous.
    # "Engineering {tag}" appears in both the GDrive folder and Slack channel;
    # "Marketing {tag}" is intentionally different.
    nodes = [
        _node(f"eng_folder_{tag}", f"Engineering {tag}", DocumentSource.GOOGLE_DRIVE),
        _node(f"eng_channel_{tag}", f"Engineering {tag}", DocumentSource.SLACK),
        _node(f"marketing_{tag}", f"Marketing {tag}", DocumentSource.CONFLUENCE),
        # STUB — must be excluded from search results even though its name matches
        _node(
            f"stub_{tag}",
            f"Engineering {tag}",
            DocumentSource.GOOGLE_DRIVE,
            HierarchyNodeType.STUB,
        ),
    ]
    for n in nodes:
        db_session.add(n)
    db_session.flush()

    yield nodes

    for n in nodes:
        db_session.delete(n)
    db_session.commit()


@pytest.fixture()
def acl_nodes(db_session: Session) -> Generator[list[HierarchyNode], None, None]:
    tag = uuid4().hex[:8]
    nodes = [
        _node(f"public_{tag}", f"Public Reports {tag}", is_public=True),
        _node(
            f"email_{tag}",
            f"Private Reports {tag}",
            is_public=False,
            external_user_emails=["alice@example.com"],
        ),
        _node(
            f"group_{tag}",
            f"Group Reports {tag}",
            is_public=False,
            external_user_group_ids=["group_eng"],
        ),
        _node(f"hidden_{tag}", f"Hidden Reports {tag}", is_public=False),
    ]
    for n in nodes:
        db_session.add(n)
    db_session.flush()

    yield nodes

    for n in nodes:
        db_session.delete(n)
    db_session.commit()


# --- Basic search behavior (MIT version) ---


def test_case_insensitive_match(
    db_session: Session, search_nodes: list[HierarchyNode]
) -> None:
    tag = search_nodes[0].raw_node_id.split("_")[-1]
    results = mit_search(db_session, f"engineering {tag}", None, "", [])
    result_ids = {n.raw_node_id for n in results}

    eng_folder, eng_channel, *_ = search_nodes
    assert eng_folder.raw_node_id in result_ids
    assert eng_channel.raw_node_id in result_ids


def test_case_insensitive_upper(
    db_session: Session, search_nodes: list[HierarchyNode]
) -> None:
    tag = search_nodes[0].raw_node_id.split("_")[-1]
    results = mit_search(db_session, f"ENGINEERING {tag}", None, "", [])
    result_ids = {n.raw_node_id for n in results}

    eng_folder, eng_channel, *_ = search_nodes
    assert eng_folder.raw_node_id in result_ids
    assert eng_channel.raw_node_id in result_ids


def test_no_match_returns_empty(db_session: Session) -> None:
    results = mit_search(db_session, "zzz_no_match_ever_zzz", None, "", [])
    assert results == []


def test_stub_nodes_excluded(
    db_session: Session, search_nodes: list[HierarchyNode]
) -> None:
    tag = search_nodes[0].raw_node_id.split("_")[-1]
    # The stub node has the same display_name as the engineering folder/channel
    results = mit_search(db_session, f"Engineering {tag}", None, "", [])
    result_ids = {n.raw_node_id for n in results}

    stub_node = search_nodes[3]
    assert stub_node.raw_node_id not in result_ids


def test_source_nodes_never_returned(db_session: Session) -> None:
    """SOURCE-type root nodes must never appear in search results."""
    source_node = get_source_hierarchy_node(db_session, DocumentSource.GOOGLE_DRIVE)
    assert source_node is not None
    # Searching by the SOURCE node's display_name would return it if the notin_ filter
    # were absent — asserting it's missing proves the filter is active.
    results = mit_search(db_session, source_node.display_name, None, "", [], 1000)
    assert all(n.id != source_node.id for n in results)


def test_source_filter_narrows_results(
    db_session: Session, search_nodes: list[HierarchyNode]
) -> None:
    tag = search_nodes[0].raw_node_id.split("_")[-1]

    gdrive_results = mit_search(
        db_session, f"Engineering {tag}", [DocumentSource.GOOGLE_DRIVE], "", []
    )
    gdrive_ids = {n.raw_node_id for n in gdrive_results}

    eng_folder, eng_channel, *_ = search_nodes
    assert eng_folder.raw_node_id in gdrive_ids
    assert eng_channel.raw_node_id not in gdrive_ids  # Slack, filtered out


def test_multi_source_filter(
    db_session: Session, search_nodes: list[HierarchyNode]
) -> None:
    tag = search_nodes[0].raw_node_id.split("_")[-1]

    results = mit_search(
        db_session,
        f"Engineering {tag}",
        [DocumentSource.GOOGLE_DRIVE, DocumentSource.SLACK],
        "",
        [],
    )
    result_ids = {n.raw_node_id for n in results}

    eng_folder, eng_channel, marketing, *_ = search_nodes
    assert eng_folder.raw_node_id in result_ids
    assert eng_channel.raw_node_id in result_ids
    assert marketing.raw_node_id not in result_ids


def test_like_metacharacters_treated_as_literals(db_session: Session) -> None:
    """% and _ in the query must be treated as literal characters, not LIKE wildcards.

    Without escaping, searching for "foo_bar" would match "fooXbar" (since _ is a
    single-character wildcard). With escaping, only "foo_bar" should match.
    """
    tag = uuid4().hex[:8]
    node_with_underscore = _node(f"under_{tag}", f"foo_bar {tag}")
    node_without_underscore = _node(f"nounder_{tag}", f"fooXbar {tag}")
    db_session.add(node_with_underscore)
    db_session.add(node_without_underscore)
    db_session.flush()

    try:
        results = mit_search(db_session, f"foo_bar {tag}", None, "", [])
        result_ids = {n.raw_node_id for n in results}

        assert node_with_underscore.raw_node_id in result_ids
        assert node_without_underscore.raw_node_id not in result_ids
    finally:
        db_session.delete(node_with_underscore)
        db_session.delete(node_without_underscore)
        db_session.commit()


# --- ACL filtering (EE version) ---


def test_ee_public_node_visible_to_all(
    db_session: Session, acl_nodes: list[HierarchyNode]
) -> None:
    tag = acl_nodes[0].raw_node_id.split("_")[-1]
    results = ee_search(db_session, f"Reports {tag}", None, "", [])
    result_ids = {n.raw_node_id for n in results}

    public_node = acl_nodes[0]
    assert public_node.raw_node_id in result_ids


def test_ee_email_gated_node(
    db_session: Session, acl_nodes: list[HierarchyNode]
) -> None:
    tag = acl_nodes[0].raw_node_id.split("_")[-1]
    public_node, email_node, group_node, hidden_node = acl_nodes

    # Alice can see the email-gated node
    results = ee_search(db_session, f"Reports {tag}", None, "alice@example.com", [])
    result_ids = {n.raw_node_id for n in results}
    assert email_node.raw_node_id in result_ids
    assert hidden_node.raw_node_id not in result_ids

    # Bob cannot
    results = ee_search(db_session, f"Reports {tag}", None, "bob@example.com", [])
    result_ids = {n.raw_node_id for n in results}
    assert email_node.raw_node_id not in result_ids


def test_ee_group_gated_node(
    db_session: Session, acl_nodes: list[HierarchyNode]
) -> None:
    tag = acl_nodes[0].raw_node_id.split("_")[-1]
    public_node, email_node, group_node, hidden_node = acl_nodes

    results = ee_search(db_session, f"Reports {tag}", None, "", ["group_eng"])
    result_ids = {n.raw_node_id for n in results}
    assert group_node.raw_node_id in result_ids
    assert hidden_node.raw_node_id not in result_ids


def test_ee_hidden_node_not_visible(
    db_session: Session, acl_nodes: list[HierarchyNode]
) -> None:
    tag = acl_nodes[0].raw_node_id.split("_")[-1]
    hidden_node = acl_nodes[3]

    results = ee_search(db_session, f"Hidden Reports {tag}", None, "", [])
    result_ids = {n.raw_node_id for n in results}
    assert hidden_node.raw_node_id not in result_ids
