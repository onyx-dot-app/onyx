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
