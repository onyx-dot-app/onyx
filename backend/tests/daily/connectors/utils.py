import os
from collections.abc import Iterator
from typing import IO, TypeVar

from pydantic import BaseModel

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.interfaces import (
    BaseConnector,
    CheckpointedConnector,
    CheckpointedConnectorWithPermSync,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    HierarchyNode,
    ImageSection,
    TabularSection,
    TextSection,
)

_ITERATION_LIMIT = 100_000

# Hierarchy IDs and names are source URLs and titles. CI logs are public, so
# failure messages name them only when a developer opts in locally.
_SHOW_HIERARCHY_IDS_ENV = "DAILY_TEST_SHOW_HIERARCHY_IDS"


def _show_hierarchy_ids() -> bool:
    return os.environ.get(_SHOW_HIERARCHY_IDS_ENV, "").lower() == "true"


def _hierarchy_detail(details: str) -> str:
    if _show_hierarchy_ids():
        return details
    return f"Set {_SHOW_HIERARCHY_IDS_ENV}=true locally to show the IDs."


CT = TypeVar("CT", bound=ConnectorCheckpoint)


class ConnectorOutput(BaseModel):
    """Structured output from loading a connector."""

    documents: list[Document]
    failures: list[ConnectorFailure]
    hierarchy_nodes: list[HierarchyNode]

    model_config = {"arbitrary_types_allowed": True}


def set_test_staging_callback(connector: BaseConnector) -> dict[str, bytes]:
    """Install an in-memory staging callback so tabular files produce file-backed
    sections in tests, the way docfetching does in production. Returns the
    {csv_file_id: bytes} map for content assertions."""
    staged: dict[str, bytes] = {}

    def _callback(content: IO[bytes], content_type: str) -> str:  # noqa: ARG001
        file_id = f"test-staged-csv-{len(staged)}"
        staged[file_id] = content.read()
        return file_id

    connector.set_raw_file_callback(_callback)
    return staged


def check_hierarchy_tree(
    documents: list[Document], hierarchy_nodes: list[HierarchyNode]
) -> None:
    """Raises when a document or a hierarchy node names a parent that the run
    did not yield. That parent would stay a STUB, and its children would go
    to the source root."""
    node_ids = {node.raw_node_id for node in hierarchy_nodes}
    for document in documents:
        parent_id = document.parent_hierarchy_raw_node_id
        if parent_id is not None and parent_id not in node_ids:
            raise AssertionError(
                "A document's parent hierarchy node was not yielded "
                f"({len(node_ids)} nodes yielded). "
                + _hierarchy_detail(
                    f"Document '{document.id}' "
                    f"(semantic_identifier='{document.semantic_identifier}') "
                    f"has parent_hierarchy_raw_node_id='{parent_id}'. "
                    f"Yielded hierarchy IDs: {node_ids}"
                )
            )
    for node in hierarchy_nodes:
        if node.raw_parent_id is not None and node.raw_parent_id not in node_ids:
            raise AssertionError(
                f"A {node.node_type.value} hierarchy node's parent was not "
                f"yielded ({len(node_ids)} nodes yielded). "
                + _hierarchy_detail(
                    f"HierarchyNode '{node.raw_node_id}' "
                    f"(display_name='{node.display_name}') has "
                    f"raw_parent_id='{node.raw_parent_id}'. "
                    f"Yielded hierarchy IDs: {node_ids}"
                )
            )


def load_all_from_connector(
    connector: CheckpointedConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    include_permissions: bool = False,
    raise_on_failures: bool = True,
) -> ConnectorOutput:
    """
    Load all documents, hierarchy nodes, and failures from a connector.

    Returns a ConnectorOutput with documents, failures, and hierarchy_nodes separated.

    Also validates the final tree: the parent of every document and every
    hierarchy node is a node that the run yielded. The order does not matter:
    indexing gives a child a STUB parent until the parent's node arrives.
    """
    num_iterations = 0

    if include_permissions and not isinstance(
        connector, CheckpointedConnectorWithPermSync
    ):
        raise ValueError("Connector does not support permission syncing")

    # Tabular files need a staging callback to produce file-backed sections;
    # docfetching installs one in production, so mirror that here.
    set_test_staging_callback(connector)

    checkpoint = connector.build_dummy_checkpoint()
    documents: list[Document] = []
    failures: list[ConnectorFailure] = []
    hierarchy_nodes: list[HierarchyNode] = []

    while checkpoint.has_more:
        load_from_checkpoint_generator = (
            connector.load_from_checkpoint_with_perm_sync
            if include_permissions
            and isinstance(connector, CheckpointedConnectorWithPermSync)
            else connector.load_from_checkpoint
        )
        doc_batch_generator = CheckpointOutputWrapper[CT]()(
            load_from_checkpoint_generator(  # ty: ignore[invalid-argument-type]
                start,
                end,
                checkpoint,  # ty: ignore[invalid-argument-type]
            )
        )

        for document, hierarchy_node, failure, next_checkpoint in doc_batch_generator:
            if hierarchy_node is not None:
                hierarchy_nodes.append(hierarchy_node)

            if failure is not None:
                failures.append(failure)

            if document is not None and isinstance(document, Document):
                documents.append(document)

            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    if raise_on_failures and failures:
        raise RuntimeError(f"Failed to load documents: {failures}")

    check_hierarchy_tree(documents, hierarchy_nodes)

    return ConnectorOutput(
        documents=documents,
        failures=failures,
        hierarchy_nodes=hierarchy_nodes,
    )


def to_sections(
    documents: list[Document],
) -> Iterator[TextSection | ImageSection | TabularSection]:
    for doc in documents:
        for section in doc.sections:
            yield section


def to_text_sections(
    sections: Iterator[TextSection | ImageSection | TabularSection],
) -> Iterator[str]:
    for section in sections:
        if isinstance(section, TextSection):
            yield section.text
