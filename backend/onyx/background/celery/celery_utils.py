from collections.abc import Generator
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import cast

import httpx

from onyx.configs.app_configs import MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE
from onyx.configs.app_configs import VESPA_REQUEST_TIMEOUT
from onyx.connectors.connector_runner import batched_doc_ids
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()
PRUNING_CHECKPOINTED_BATCH_SIZE = 32


def document_batch_to_ids(
    doc_batch: Iterator[list[Document]] | Iterator[list[SlimDocument]],
) -> Generator[set[str], None, None]:
    for doc_list in doc_batch:
        yield {doc.id for doc in doc_list}


def extract_ids_from_runnable_connector(
    runnable_connector: BaseConnector,
    callback: IndexingHeartbeatInterface | None = None,
) -> set[str]:
    """
    If the given connector is neither a SlimConnector nor a SlimConnectorWithPermSync, just pull
    all docs using the load_from_state and grab out the IDs.

    Optionally, a callback can be passed to handle the length of each document batch.
    """
    all_connector_doc_ids: set[str] = set()

    doc_batch_id_generator = None
    if isinstance(runnable_connector, SlimConnector):
        doc_batch_id_generator = document_batch_to_ids(
            runnable_connector.retrieve_all_slim_docs()
        )
    elif isinstance(runnable_connector, SlimConnectorWithPermSync):
        doc_batch_id_generator = document_batch_to_ids(
            runnable_connector.retrieve_all_slim_docs_perm_sync()
        )
    # If the connector isn't slim, fall back to running it normally to get ids
    elif isinstance(runnable_connector, LoadConnector):
        doc_batch_id_generator = document_batch_to_ids(
            runnable_connector.load_from_state()
        )
    elif isinstance(runnable_connector, PollConnector):
        start = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime.now(timezone.utc).timestamp()
        doc_batch_id_generator = document_batch_to_ids(
            runnable_connector.poll_source(start=start, end=end)
        )
    elif isinstance(runnable_connector, CheckpointedConnector):
        start = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime.now(timezone.utc).timestamp()
        checkpoint = runnable_connector.build_dummy_checkpoint()
        checkpoint_generator = runnable_connector.load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint
        )
        doc_batch_id_generator = batched_doc_ids(
            checkpoint_generator, batch_size=PRUNING_CHECKPOINTED_BATCH_SIZE
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

    for doc_batch_ids in doc_batch_id_generator:
        if callback:
            if callback.should_stop():
                raise RuntimeError(
                    "extract_ids_from_runnable_connector: Stop signal detected"
                )

        all_connector_doc_ids.update(doc_batch_processing_func(doc_batch_ids))

        if callback:
            callback.progress("extract_ids_from_runnable_connector", len(doc_batch_ids))

    return all_connector_doc_ids


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
