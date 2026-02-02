from collections.abc import Iterator
from typing import TypeVar

from pydantic import BaseModel

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection

_ITERATION_LIMIT = 100_000

CT = TypeVar("CT", bound=ConnectorCheckpoint)


class ConnectorOutput(BaseModel):
    """Structured output from loading a connector."""

    documents: list[Document]
    failures: list[ConnectorFailure]
    hierarchy_nodes: list[HierarchyNode]

    model_config = {"arbitrary_types_allowed": True}


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

    Also validates that parent hierarchy nodes are always yielded before their children:
    - For documents: parent must have been yielded before the document
    - For hierarchy nodes: after each batch, validates that all parents in the batch
      have been seen (either in the current batch or a previous batch)
    """
    num_iterations = 0

    if include_permissions and not isinstance(
        connector, CheckpointedConnectorWithPermSync
    ):
        raise ValueError("Connector does not support permission syncing")

    checkpoint = connector.build_dummy_checkpoint()
    documents: list[Document] = []
    failures: list[ConnectorFailure] = []
    hierarchy_nodes: list[HierarchyNode] = []

    # Track all seen hierarchy node raw_ids for parent validation
    seen_hierarchy_raw_ids: set[str] = set()

    while checkpoint.has_more:
        load_from_checkpoint_generator = (
            connector.load_from_checkpoint_with_perm_sync
            if include_permissions
            and isinstance(connector, CheckpointedConnectorWithPermSync)
            else connector.load_from_checkpoint
        )
        doc_batch_generator = CheckpointOutputWrapper[CT]()(
            load_from_checkpoint_generator(start, end, checkpoint)
        )

        # Collect hierarchy nodes from this batch (for end-of-batch validation)
        batch_hierarchy_nodes: list[HierarchyNode] = []

        for document, hierarchy_node, failure, next_checkpoint in doc_batch_generator:
            if hierarchy_node is not None:
                hierarchy_nodes.append(hierarchy_node)
                batch_hierarchy_nodes.append(hierarchy_node)
                # Add to seen set immediately so subsequent documents can reference it
                seen_hierarchy_raw_ids.add(hierarchy_node.raw_node_id)

            if failure is not None:
                failures.append(failure)

            if document is not None and isinstance(document, Document):
                documents.append(document)
                # Validate: document's parent must have been yielded before this document
                if document.parent_hierarchy_raw_node_id is not None:
                    if (
                        document.parent_hierarchy_raw_node_id
                        not in seen_hierarchy_raw_ids
                    ):
                        raise AssertionError(
                            f"Document '{document.id}' "
                            f"(semantic_identifier='{document.semantic_identifier}') "
                            f"has parent_hierarchy_raw_node_id="
                            f"'{document.parent_hierarchy_raw_node_id}' "
                            f"which was not yielded before this document. "
                            f"Seen hierarchy IDs: {seen_hierarchy_raw_ids}"
                        )

            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        # End-of-batch validation for hierarchy nodes:
        # Each node's parent must be in the current batch or a previous batch
        batch_hierarchy_raw_ids = {node.raw_node_id for node in batch_hierarchy_nodes}
        for node in batch_hierarchy_nodes:
            if node.raw_parent_id is None:
                continue  # Root nodes have no parent

            parent_in_current_batch = node.raw_parent_id in batch_hierarchy_raw_ids
            parent_in_previous_batch = node.raw_parent_id in seen_hierarchy_raw_ids

            if not parent_in_current_batch and not parent_in_previous_batch:
                raise AssertionError(
                    f"HierarchyNode '{node.raw_node_id}' "
                    f"(display_name='{node.display_name}') "
                    f"has raw_parent_id='{node.raw_parent_id}' which was not yielded "
                    f"in the current batch or any previous batch. "
                    f"Seen hierarchy IDs: {seen_hierarchy_raw_ids}, "
                    f"Current batch IDs: {batch_hierarchy_raw_ids}"
                )

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    if raise_on_failures and failures:
        raise RuntimeError(f"Failed to load documents: {failures}")

    return ConnectorOutput(
        documents=documents,
        failures=failures,
        hierarchy_nodes=hierarchy_nodes,
    )


def to_sections(
    documents: list[Document],
) -> Iterator[TextSection | ImageSection]:
    for doc in documents:
        for section in doc.sections:
            yield section


def to_text_sections(sections: Iterator[TextSection | ImageSection]) -> Iterator[str]:
    for section in sections:
        if isinstance(section, TextSection):
            yield section.text
