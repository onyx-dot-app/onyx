from typing import cast
from typing import TypeVar

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.interfaces import CheckpointConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document

_ITERATION_LIMIT = 100_000

CT = TypeVar("CT", bound=ConnectorCheckpoint)


def load_all_docs_from_checkpoint_connector(
    connector: CheckpointConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[Document]:
    num_iterations = 0

    checkpoint = cast(CT, connector.build_dummy_checkpoint())
    documents: list[Document] = []
    while checkpoint.has_more:
        doc_batch_generator = CheckpointOutputWrapper[CT]()(
            connector.load_from_checkpoint(start, end, checkpoint)
        )
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                raise RuntimeError(f"Failed to load documents: {failure}")
            if document is not None:
                documents.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    return documents


def load_everything_from_checkpoint_connector(
    connector: CheckpointConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[Document | ConnectorFailure]:
    """Like load_all_docs_from_checkpoint_connector but returns both documents and failures"""
    num_iterations = 0

    checkpoint = connector.build_dummy_checkpoint()
    outputs: list[Document | ConnectorFailure] = []
    while checkpoint.has_more:
        doc_batch_generator = CheckpointOutputWrapper[CT]()(
            connector.load_from_checkpoint(start, end, checkpoint)
        )
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                outputs.append(failure)
            if document is not None:
                outputs.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    return outputs
