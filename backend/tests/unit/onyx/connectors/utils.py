from typing import cast
from typing import Generic
from typing import TypeVar

from pydantic import BaseModel

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document

_ITERATION_LIMIT = 100_000


CT = TypeVar("CT", bound=ConnectorCheckpoint)


class SingleConnectorCallOutput(BaseModel, Generic[CT]):
    items: list[Document | ConnectorFailure]
    next_checkpoint: CT


def load_everything_from_checkpoint_connector(
    connector: CheckpointedConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[SingleConnectorCallOutput[CT]]:

    checkpoint = cast(CT, connector.build_dummy_checkpoint())
    return load_everything_from_checkpoint_connector_from_checkpoint(
        connector, start, end, checkpoint
    )


def load_everything_from_checkpoint_connector_from_checkpoint(
    connector: CheckpointedConnector[CT],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    checkpoint: CT,
) -> list[SingleConnectorCallOutput[CT]]:
    num_iterations = 0
    outputs: list[SingleConnectorCallOutput[CT]] = []
    while checkpoint.has_more:
        items: list[Document | ConnectorFailure] = []
        doc_batch_generator = CheckpointOutputWrapper[CT]()(
            connector.load_from_checkpoint(start, end, checkpoint)
        )
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                items.append(failure)
            if document is not None:
                items.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        outputs.append(
            SingleConnectorCallOutput(items=items, next_checkpoint=checkpoint)
        )

        num_iterations += 1
        if num_iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")

    return outputs
