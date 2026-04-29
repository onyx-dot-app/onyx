import time
from collections.abc import Generator
from collections.abc import Iterator
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import cast
from typing import TypeVar

import httpx
from pydantic import BaseModel

from onyx.configs.app_configs import MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE
from onyx.configs.app_configs import VESPA_REQUEST_TIMEOUT
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.server.metrics.pruning_metrics import inc_pruning_rate_limit_error
from onyx.server.metrics.pruning_metrics import observe_pruning_enumeration_duration
from onyx.utils.logger import setup_logger

logger = setup_logger()

CT = TypeVar("CT", bound=ConnectorCheckpoint)


class SlimConnectorExtractionResult(BaseModel):
    """Result of extracting document IDs and hierarchy nodes from a connector.

    raw_id_to_parent maps document ID → parent_hierarchy_raw_node_id (or None).
    Use raw_id_to_parent.keys() wherever the old set of IDs was needed.
    """

    raw_id_to_parent: dict[str, str | None]
    hierarchy_nodes: list[HierarchyNode]


def _checkpointed_batched_items(
    connector: CheckpointedConnector[CT],
    start: float,
    end: float,
) -> Generator[list[Document | HierarchyNode | ConnectorFailure], None, None]:
    """Loop through all checkpoint steps and yield batched items.

    Some checkpointed connectors (e.g. IMAP) are multi-step: the first
    checkpoint call may only initialize internal state without yielding
    any documents. This function loops until checkpoint.has_more is False
    to ensure all items are collected across every step.
    """
    checkpoint = connector.build_dummy_checkpoint()
    while True:
        checkpoint_output = connector.load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint
        )
        wrapper: CheckpointOutputWrapper[CT] = CheckpointOutputWrapper()
        batch: list[Document | HierarchyNode | ConnectorFailure] = []
        for document, hierarchy_node, failure, next_checkpoint in wrapper(
            checkpoint_output
        ):
            if document is not None:
                batch.append(document)
            elif hierarchy_node is not None:
                batch.append(hierarchy_node)
            elif failure is not None:
                batch.append(failure)

            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        if batch:
            yield batch

        if not checkpoint.has_more:
            break


def _get_failure_id(failure: ConnectorFailure) -> str | None:
    """Extract the document/entity ID from a ConnectorFailure."""
    if failure.failed_document:
        return failure.failed_document.document_id
    if failure.failed_entity:
        return failure.failed_entity.entity_id
    return None


class BatchResult(BaseModel):
    raw_id_to_parent: dict[str, str | None]
    hierarchy_nodes: list[HierarchyNode]


def _extract_from_batch(
    doc_list: Sequence[Document | SlimDocument | HierarchyNode | ConnectorFailure],
) -> BatchResult:
    """Separate a batch into document IDs (with parent mapping) and hierarchy nodes.

    ConnectorFailure items have their failed document/entity IDs added to the
    ID dict so that failed-to-retrieve documents are not accidentally pruned.
    """
    ids: dict[str, str | None] = {}
    hierarchy_nodes: list[HierarchyNode] = []
    for item in doc_list:
        if isinstance(item, HierarchyNode):
            hierarchy_nodes.append(item)
        elif isinstance(item, ConnectorFailure):
            failed_id = _get_failure_id(item)
            if failed_id:
                ids[failed_id] = None
            logger.warning(
                f"Failed to retrieve document {failed_id}: {item.failure_message}"
            )
        else:
            ids[item.id] = item.parent_hierarchy_raw_node_id
    return BatchResult(raw_id_to_parent=ids, hierarchy_nodes=hierarchy_nodes)


def extract_ids_from_runnable_connector(
    runnable_connector: BaseConnector,
    callback: IndexingHeartbeatInterface | None = None,
    connector_type: str = "unknown",
) -> SlimConnectorExtractionResult:
    """
    Extract document IDs and hierarchy nodes from a runnable connector.

    Hierarchy nodes yielded alongside documents/slim docs are collected and
    returned in the result. ConnectorFailure items have their IDs preserved
    so that failed-to-retrieve documents are not accidentally pruned.

    Optionally, a callback can be passed to handle the length of each document batch.
    """
    all_raw_id_to_parent: dict[str, str | None] = {}
    all_hierarchy_nodes: list[HierarchyNode] = []

    # Sequence (covariant) lets all the specific list[...] iterator types unify here
    raw_batch_generator: (
        Iterator[Sequence[Document | SlimDocument | HierarchyNode | ConnectorFailure]]
        | None
    ) = None

    if isinstance(runnable_connector, SlimConnector):
        raw_batch_generator = runnable_connector.retrieve_all_slim_docs()
    elif isinstance(runnable_connector, SlimConnectorWithPermSync):
        raw_batch_generator = runnable_connector.retrieve_all_slim_docs_perm_sync()
    # If the connector isn't slim, fall back to running it normally to get ids
    elif isinstance(runnable_connector, LoadConnector):
        raw_batch_generator = runnable_connector.load_from_state()
    elif isinstance(runnable_connector, PollConnector):
        start = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime.now(timezone.utc).timestamp()
        raw_batch_generator = runnable_connector.poll_source(start=start, end=end)
    elif isinstance(runnable_connector, CheckpointedConnector):
        start = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime.now(timezone.utc).timestamp()
        raw_batch_generator = _checkpointed_batched_items(
            runnable_connector, start, end
        )
    else:
        raise RuntimeError("Pruning job could not find a valid runnable_connector.")

    # this function is called per batch for rate limiting
    doc_batch_processing_func = (
        rate_limit_builder(
            max_calls=MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE, period=60
        )(lambda x: x)
        if MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE
        else lambda x: x
    )

    # process raw batches to extract both IDs and hierarchy nodes
    enumeration_start = time.monotonic()
    try:
        for doc_list in raw_batch_generator:
            if callback and callback.should_stop():
                raise RuntimeError(
                    "extract_ids_from_runnable_connector: Stop signal detected"
                )

            batch_result = _extract_from_batch(doc_list)
            batch_ids = batch_result.raw_id_to_parent
            batch_nodes = batch_result.hierarchy_nodes
            doc_batch_processing_func(batch_ids)
            all_raw_id_to_parent.update(batch_ids)
            all_hierarchy_nodes.extend(batch_nodes)

            if callback:
                callback.progress("extract_ids_from_runnable_connector", len(batch_ids))
    except Exception as e:
        # Best-effort rate limit detection via string matching.
        # Connectors surface rate limits inconsistently — some raise HTTP 429,
        # some use SDK-specific exceptions (e.g. google.api_core.exceptions.ResourceExhausted)
        # that may or may not include "rate limit" or "429" in the message.
        # TODO(Bo): replace with a standard ConnectorRateLimitError exception that all
        # connectors raise when rate limited, making this check precise.
        error_str = str(e)
        if "rate limit" in error_str.lower() or "429" in error_str:
            inc_pruning_rate_limit_error(connector_type)
        raise
    finally:
        observe_pruning_enumeration_duration(
            time.monotonic() - enumeration_start, connector_type
        )

    return SlimConnectorExtractionResult(
        raw_id_to_parent=all_raw_id_to_parent,
        hierarchy_nodes=all_hierarchy_nodes,
    )


def celery_is_listening_to_queue(worker: Any, name: str) -> bool:
    """Checks to see if we're listening to the named queue"""

    # how to get a list of queues this worker is listening to
    # https://stackoverflow.com/questions/29790523/how-to-determine-which-queues-a-celery-worker-is-consuming-at-runtime
    queue_names = list(worker.app.amqp.queues.consume_from.keys())
    for queue_name in queue_names:
        if queue_name == name:
            return True

    return False


def celery_is_worker_primary(worker: Any) -> bool:
    """There are multiple approaches that could be taken to determine if a celery worker
    is 'primary', as defined by us. But the way we do it is to check the hostname set
    for the celery worker, which can be done on the
    command line with '--hostname'."""
    hostname = worker.hostname
    if hostname.startswith("primary"):
        return True

    return False


def httpx_init_vespa_pool(
    max_keepalive_connections: int,
    timeout: int = VESPA_REQUEST_TIMEOUT,
    ssl_cert: str | None = None,
    ssl_key: str | None = None,
) -> None:
    httpx_cert = None
    httpx_verify = False
    if ssl_cert and ssl_key:
        httpx_cert = cast(tuple[str, str], (ssl_cert, ssl_key))
        httpx_verify = True

    HttpxPool.init_client(
        name="vespa",
        cert=httpx_cert,
        verify=httpx_verify,
        timeout=timeout,
        http2=False,
        limits=httpx.Limits(max_keepalive_connections=max_keepalive_connections),
    )


def make_probe_path(probe: str, hostname: str) -> Path:
    """templates the path for a k8s probe file.

    e.g. /tmp/onyx_k8s_indexing_readiness.txt
    """
    hostname_parts = hostname.split("@")
    if len(hostname_parts) != 2:
        raise ValueError(f"hostname could not be split! {hostname=}")

    name = hostname_parts[0]
    if not name:
        raise ValueError(f"name cannot be empty! {name=}")

    safe_name = "".join(c for c in name if c.isalnum()).rstrip()
    return Path(f"/tmp/onyx_k8s_{safe_name}_{probe}.txt")
