from collections.abc import Callable
from collections.abc import Iterator
from typing import cast
from typing import TypeVar

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection

_ITERATION_LIMIT = 100_000

CT = TypeVar("CT", bound=ConnectorCheckpoint)
LoadFunction = Callable[[CT], CheckpointOutput[CT]]


def _load_all_docs(
    connector: CheckpointedConnector[CT],
    load: LoadFunction,
) -> list[Document]:
    num_iterations = 0

    checkpoint = cast(CT, connector.build_dummy_checkpoint())
    documents: list[Document] = []
    while checkpoint.has_more:
        doc_batch_generator = CheckpointOutputWrapper[CT]()(load(checkpoint))
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                raise RuntimeError(f"Failed to load documents: {failure}")
            if document is not None and isinstance(document, Document):
                documents.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    return documents


def load_all_docs_from_checkpoint_connector_with_perm_sync(
    connector: CheckpointedConnectorWithPermSync[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[Document]:
    return _load_all_docs(
        connector=connector,
        load=lambda checkpoint: connector.load_from_checkpoint_with_perm_sync(
            start=start, end=end, checkpoint=checkpoint
        ),
    )


def load_all_docs_from_checkpoint_connector(
    connector: CheckpointedConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[Document]:
    return _load_all_docs(
        connector=connector,
        load=lambda checkpoint: connector.load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint
        ),
    )


def load_everything_from_checkpoint_connector(
    connector: CheckpointedConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    include_permissions: bool = False,
) -> list[Document | ConnectorFailure]:
    """Like load_all_docs_from_checkpoint_connector but returns both documents and failures"""
    num_iterations = 0

    if include_permissions and not isinstance(
        connector, CheckpointedConnectorWithPermSync
    ):
        raise ValueError("Connector does not support permission syncing")

    checkpoint = connector.build_dummy_checkpoint()
    outputs: list[Document | ConnectorFailure] = []
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
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                outputs.append(failure)
            if document is not None and isinstance(document, Document):
                outputs.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    return outputs


def to_sections(
    iterator: Iterator[Document | ConnectorFailure],
) -> Iterator[TextSection | ImageSection]:
    for doc in iterator:
        if not isinstance(doc, Document):
            failure = doc
            raise RuntimeError(failure)

        for section in doc.sections:
            yield section


def to_text_sections(iterator: Iterator[TextSection | ImageSection]) -> Iterator[str]:
    for section in iterator:
        if isinstance(section, TextSection):
            yield section.text


def to_documents(
    iterator: Iterator[Document | ConnectorFailure],
) -> Iterator[Document]:
    for doc in iterator:
        if not isinstance(doc, Document):
            failure = doc
            raise RuntimeError(failure)

        yield doc
