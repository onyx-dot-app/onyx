"""Breaks a cc-pair's documents down by hierarchy node for its status page."""

import pydantic
from sqlalchemy.orm import Session

from onyx.connectors.connector_config import (
    ConnectorConfig,
    HierarchyBreakdownSection,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.document import get_indexed_documents_for_cc_pair_with_id_containing
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import (
    get_hierarchy_nodes_for_cc_pair,
    get_source_hierarchy_node,
    get_subtree_document_counts_for_cc_pair,
)
from onyx.db.index_attempt import cc_pair_has_successful_index_attempt
from onyx.db.models import ConnectorCredentialPair, Document, HierarchyNode
from onyx.server.documents.models import (
    CCPairHierarchyBreakdown,
    HierarchyBreakdownEntry,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_breakdown_sections(
    config_class: type[ConnectorConfig], cc_pair: ConnectorCredentialPair
) -> list[HierarchyBreakdownSection] | None:
    try:
        config = config_class.model_validate(
            cc_pair.connector.connector_specific_config
        )
    except pydantic.ValidationError as e:
        # Rows written before typed configs existed may not conform.
        logger.warning(
            "Connector config does not match %s, so the hierarchy breakdown uses "
            "the top-level nodes: cc_pair_id=%s errors=%s",
            config_class.__name__,
            cc_pair.id,
            e,
        )
        return None
    return config.hierarchy_breakdown_sections()


def _get_top_level_sections(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> tuple[list[HierarchyBreakdownSection], list[HierarchyNode]]:
    source_node = get_source_hierarchy_node(db_session, cc_pair.connector.source)
    if source_node is None:
        return [], []
    nodes = get_hierarchy_nodes_for_cc_pair(
        db_session,
        cc_pair.connector_id,
        cc_pair.credential_id,
        parent_id=source_node.id,
    )
    node_types = {node.node_type for node in nodes}
    sections = [
        HierarchyBreakdownSection(node_type=node_type)
        for node_type in HierarchyNodeType
        if node_type in node_types
    ]
    return sections, nodes


def _normalize_key(section: HierarchyBreakdownSection, key: str) -> str:
    return key.casefold() if section.case_insensitive_keys else key


def _is_expected(section: HierarchyBreakdownSection, key: str) -> bool:
    return _normalize_key(section, key) in {
        _normalize_key(section, expected) for expected in section.expected_node_keys
    }


def _find_standalone_documents(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    config_class: type[ConnectorConfig],
    section: HierarchyBreakdownSection,
    missing_keys: list[str],
) -> dict[str, Document]:
    """Expected key -> the indexed document that stands for a node without a
    hierarchy node (e.g. a Confluence page with no children). The document id
    is the node's raw id, so the config's key function maps it to the key."""
    if not section.nodes_can_be_documents:
        return {}
    found: dict[str, Document] = {}
    for key in missing_keys:
        for document in get_indexed_documents_for_cc_pair_with_id_containing(
            db_session, cc_pair.connector_id, cc_pair.credential_id, key
        ):
            document_key = config_class.hierarchy_node_key(
                section.node_type, document.id
            )
            if _normalize_key(section, document_key) == _normalize_key(section, key):
                found[key] = document
                break
    return found


def _get_doc_count(document_count: int, *, is_expected: bool) -> int | None:
    """A configured node without documents shows as not indexed (None). Other
    nodes show their count, also 0."""
    if is_expected and document_count == 0:
        return None
    return document_count


def _sort_key(entry: HierarchyBreakdownEntry) -> tuple[bool, int, str]:
    # Most documents first, then the nodes without documents.
    return (entry.doc_count is None, -(entry.doc_count or 0), entry.raw_node_id)


def build_cc_pair_hierarchy_breakdown(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> CCPairHierarchyBreakdown | None:
    """None until the cc-pair has a successful index attempt. The connector's
    ``ConnectorConfig.hierarchy_breakdown_sections`` picks the node types.
    ``other_doc_count`` holds the indexed documents that no listed row covers,
    so every document is in a row or in "other". "Successful" means one full
    run succeeded, under any search settings."""
    if not cc_pair_has_successful_index_attempt(db_session, cc_pair.id):
        return None

    mapping = CONNECTOR_CLASS_MAP.get(cc_pair.connector.source)
    config_class = mapping.config_class if mapping else ConnectorConfig
    sections = _get_breakdown_sections(config_class, cc_pair)
    if sections is None:
        sections, nodes = _get_top_level_sections(db_session, cc_pair)
    else:
        nodes = get_hierarchy_nodes_for_cc_pair(
            db_session,
            cc_pair.connector_id,
            cc_pair.credential_id,
            node_types=[section.node_type for section in sections],
        )

    nodes_by_section: dict[HierarchyNodeType, dict[str, HierarchyNode]] = {}
    for section in sections:
        keyed_nodes = {
            config_class.hierarchy_node_key(node.node_type, node.raw_node_id): node
            for node in nodes
            if node.node_type == section.node_type
        }
        if not section.include_unexpected_nodes:
            keyed_nodes = {
                key: node
                for key, node in keyed_nodes.items()
                if _is_expected(section, key)
            }
        nodes_by_section[section.node_type] = keyed_nodes

    standalone_by_section: dict[HierarchyNodeType, dict[str, Document]] = {}
    for section in sections:
        found_keys = {
            _normalize_key(section, key) for key in nodes_by_section[section.node_type]
        }
        standalone_by_section[section.node_type] = _find_standalone_documents(
            db_session,
            cc_pair,
            config_class,
            section,
            [
                key
                for key in section.expected_node_keys
                if _normalize_key(section, key) not in found_keys
            ],
        )

    document_counts = get_subtree_document_counts_for_cc_pair(
        db_session,
        cc_pair.connector_id,
        cc_pair.credential_id,
        root_node_ids={
            node.id
            for keyed_nodes in nodes_by_section.values()
            for node in keyed_nodes.values()
        },
        standalone_document_ids={
            document.id
            for standalone in standalone_by_section.values()
            for document in standalone.values()
        },
    )

    nodes_by_type: dict[HierarchyNodeType, list[HierarchyBreakdownEntry]] = {}
    for section in sections:
        keyed_nodes = nodes_by_section[section.node_type]
        standalone = standalone_by_section[section.node_type]
        entries = [
            HierarchyBreakdownEntry(
                raw_node_id=key,
                display_name=node.display_name,
                link=node.link,
                doc_count=_get_doc_count(
                    document_counts.by_root.get(node.id, 0),
                    is_expected=_is_expected(section, key),
                ),
            )
            for key, node in keyed_nodes.items()
        ]
        entries.extend(
            HierarchyBreakdownEntry(
                raw_node_id=key,
                display_name=document.semantic_id,
                link=document.link,
                doc_count=1,
            )
            for key, document in standalone.items()
        )
        found_keys = {_normalize_key(section, key) for key in keyed_nodes}
        entries.extend(
            HierarchyBreakdownEntry(
                raw_node_id=key, display_name=None, link=None, doc_count=None
            )
            for key in section.expected_node_keys
            if _normalize_key(section, key) not in found_keys and key not in standalone
        )
        if entries:
            nodes_by_type[section.node_type] = sorted(entries, key=_sort_key)
    return CCPairHierarchyBreakdown(
        nodes_by_type=nodes_by_type, other_doc_count=document_counts.other
    )
