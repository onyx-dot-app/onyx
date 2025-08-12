import sys
import time
from collections.abc import Generator
from datetime import datetime
from typing import Generic
from typing import TypeVar

from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger


logger = setup_logger()


TimeRange = tuple[datetime, datetime]

CT = TypeVar("CT", bound=ConnectorCheckpoint)


def batched_doc_ids(
    checkpoint_connector_generator: CheckpointOutput[CT],
    batch_size: int,
) -> Generator[set[str], None, None]:
    batch: set[str] = set()
    for document, failure, next_checkpoint in CheckpointOutputWrapper[CT]()(
        checkpoint_connector_generator
    ):
        if document is not None:
            batch.add(document.id)
        elif (
            failure and failure.failed_document and failure.failed_document.document_id
        ):
            batch.add(failure.failed_document.document_id)

        if len(batch) >= batch_size:
            yield batch
            batch = set()
    if len(batch) > 0:
        yield batch


class CheckpointOutputWrapper(Generic[CT]):
    """
    Wraps a CheckpointOutput generator to give things back in a more digestible format,
    specifically for Document outputs.
    The connector format is easier for the connector implementor (e.g. it enforces exactly
    one new checkpoint is returned AND that the checkpoint is at the end), thus the different
    formats.
    """

    def __init__(self) -> None:
        self.next_checkpoint: CT | None = None

    def __call__(
        self,
        checkpoint_connector_generator: CheckpointOutput[CT],
    ) -> Generator[
        tuple[Document | None, ConnectorFailure | None, CT | None],
        None,
        None,
    ]:
        # grabs the final return value and stores it in the `next_checkpoint` variable
        def _inner_wrapper(
            checkpoint_connector_generator: CheckpointOutput[CT],
        ) -> CheckpointOutput[CT]:
            self.next_checkpoint = yield from checkpoint_connector_generator
            return self.next_checkpoint  # not used

        for document_or_failure in _inner_wrapper(checkpoint_connector_generator):
            if isinstance(document_or_failure, Document):
                yield document_or_failure, None, None
            elif isinstance(document_or_failure, ConnectorFailure):
                yield None, document_or_failure, None
            else:
                raise ValueError(
                    f"Invalid document_or_failure type: {type(document_or_failure)}"
                )

        if self.next_checkpoint is None:
            raise RuntimeError(
                "Checkpoint is None. This should never happen - the connector should always return a checkpoint."
            )

        yield None, None, self.next_checkpoint


class ConnectorRunner(Generic[CT]):
    """
    Handles:
        - Batching
        - Additional exception logging
        - Combining different connector types to a single interface
    """

    def __init__(
        self,
        connector: BaseConnector,
        batch_size: int,
        # cannot be True for non-checkpointed connectors
        include_permissions: bool,
        time_range: TimeRange | None = None,
    ):
        if not isinstance(connector, CheckpointedConnector) and include_permissions:
            raise ValueError(
                "include_permissions cannot be True for non-checkpointed connectors"
            )

        self.connector = connector
        self.time_range = time_range
        self.batch_size = batch_size
        self.include_permissions = include_permissions

        self.doc_batch: list[Document] = []

    def run(self, checkpoint: CT) -> Generator[
        tuple[list[Document] | None, ConnectorFailure | None, CT | None],
        None,
        None,
    ]:
        """Adds additional exception logging to the connector."""
        try:
            if isinstance(self.connector, CheckpointedConnector):
                if self.time_range is None:
                    raise ValueError("time_range is required for CheckpointedConnector")

                start = time.monotonic()
                if self.include_permissions:
                    if not isinstance(
                        self.connector, CheckpointedConnectorWithPermSync
                    ):
                        raise ValueError(
                            "Connector does not support permission syncing"
                        )
                    load_from_checkpoint = (
                        self.connector.load_from_checkpoint_with_perm_sync
                    )
                else:
                    load_from_checkpoint = self.connector.load_from_checkpoint
                checkpoint_connector_generator = load_from_checkpoint(
                    start=self.time_range[0].timestamp(),
                    end=self.time_range[1].timestamp(),
                    checkpoint=checkpoint,
                )
                next_checkpoint: CT | None = None
                # this is guaranteed to always run at least once with next_checkpoint being non-None
                for document, failure, next_checkpoint in CheckpointOutputWrapper[CT]()(
                    checkpoint_connector_generator
                ):
                    if document is not None and isinstance(document, Document):
                        self.doc_batch.append(document)

                    if failure is not None:
                        yield None, failure, None

                    if len(self.doc_batch) >= self.batch_size:
                        yield self.doc_batch, None, None
                        self.doc_batch = []

                # yield remaining documents
                if len(self.doc_batch) > 0:
                    yield self.doc_batch, None, None
                    self.doc_batch = []

                yield None, None, next_checkpoint

                logger.debug(
                    f"Connector took {time.monotonic() - start} seconds to get to the next checkpoint."
                )

            else:
                finished_checkpoint = self.connector.build_dummy_checkpoint()
                finished_checkpoint.has_more = False

                if isinstance(self.connector, PollConnector):
                    if self.time_range is None:
                        raise ValueError("time_range is required for PollConnector")

                    for document_batch in self.connector.poll_source(
                        start=self.time_range[0].timestamp(),
                        end=self.time_range[1].timestamp(),
                    ):
                        yield document_batch, None, None

                    yield None, None, finished_checkpoint
                elif isinstance(self.connector, LoadConnector):
                    for document_batch in self.connector.load_from_state():
                        yield document_batch, None, None

                    yield None, None, finished_checkpoint
                else:
                    raise ValueError(f"Invalid connector. type: {type(self.connector)}")
        except Exception:
            exc_type, _, exc_traceback = sys.exc_info()

            # Traverse the traceback to find the last frame where the exception was raised
            tb = exc_traceback
            if tb is None:
                logger.error("No traceback found for exception")
                raise

            while tb.tb_next:
                tb = tb.tb_next  # Move to the next frame in the traceback

            # Get the local variables from the frame where the exception occurred
            local_vars = tb.tb_frame.f_locals
            local_vars_str = "\n".join(
                f"{key}: {value}" for key, value in local_vars.items()
            )
            logger.error(
                f"Error in connector. type: {exc_type};\n"
                f"local_vars below -> \n{local_vars_str[:1024]}"
            )
            raise
