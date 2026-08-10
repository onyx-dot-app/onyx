"""Run pruning's connector enumeration in a spawned child process.

Multi-hour enumerations ratchet the long-lived heavy worker's RSS — allocator
retention is only fully released on process exit — so the crawl runs in an
ephemeral child (docfetching's `SimpleJobClient` pattern). The celery task
stays behind as the watchdog: it renews the redis lock, kills the child on
stop or timeout, and reads the result from a schema-validated JSON file
(mp queues deadlock on multi-MB payloads; `run_in_isolated_process` would
block this thread for the child's whole lifetime).
"""

import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from onyx.background.celery.celery_utils import (
    SlimConnectorExtractionResult,
    extract_ids_from_runnable_connector,
)
from onyx.background.indexing.job_client import SimpleJob, SimpleJobClient
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.utils.logger import pruning_ctx, setup_logger
from onyx.utils.os_reaper import reap_exited_children
from shared_configs.configs import SENTRY_CELERY_TRACES_SAMPLE_RATE, SENTRY_DSN

logger = setup_logger()

_WATCHDOG_POLL_SECONDS = 5
_LOCK_REACQUIRE_INTERVAL_SECONDS = 60
_TERMINATE_GRACE_SECONDS = 10


class PruneEnumerationError(RuntimeError):
    """Raised when the spawned enumeration child fails, is stopped, or times out."""


class SpawnedPruneCallback(IndexingHeartbeatInterface):
    """Child-side heartbeat: liveness, stop fence, and orphan reaping.

    A raise out of the enumeration means no result file is written, so a
    partial enumeration can never be mistaken for a complete one.
    """

    def __init__(self, redis_connector: RedisConnector):
        super().__init__()
        self.redis_connector = redis_connector

    def should_stop(self) -> bool:
        return bool(self.redis_connector.stop.fenced)

    def progress(self, tag: str, amount: int) -> None:  # noqa: ARG002
        self.redis_connector.prune.set_active()
        reap_exited_children()


def pruning_enumeration_task(
    result_path: str,
    cc_pair_id: int,
    connector_id: int,
    credential_id: int,
    tenant_id: str,
) -> None:
    """Child entrypoint: enumerate all doc IDs / hierarchy nodes and write the
    `SlimConnectorExtractionResult` JSON to `result_path` (atomic rename)."""
    # spawned via SimpleJobClient, so init Sentry ourselves (mirrors _docfetching_task)
    if SENTRY_DSN:
        from onyx.configs.sentry import init_sentry

        init_sentry(traces_sample_rate=SENTRY_CELERY_TRACES_SAMPLE_RATE)

    pruning_ctx_dict = pruning_ctx.get()
    pruning_ctx_dict["cc_pair_id"] = cc_pair_id
    pruning_ctx.set(pruning_ctx_dict)

    logger.info(
        "Pruning enumeration child starting: tenant=%s cc_pair=%s",
        tenant_id,
        cc_pair_id,
    )

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    with get_session_with_current_tenant() as db_session:
        cc_pair = get_connector_credential_pair(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
        )
        if not cc_pair:
            raise RuntimeError(f"cc_pair not found for {connector_id} {credential_id}")

        connector_type = cc_pair.connector.source.value
        runnable_connector = instantiate_connector(
            db_session,
            cc_pair.connector.source,
            InputType.SLIM_RETRIEVAL,
            cc_pair.connector.connector_specific_config,
            cc_pair.credential,
        )
    # session closed — no DB connection held during the crawl

    callback = SpawnedPruneCallback(redis_connector)

    extraction_result = extract_ids_from_runnable_connector(
        runnable_connector, callback, connector_type=connector_type
    )

    tmp_path = f"{result_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(extraction_result.model_dump_json())
    os.replace(tmp_path, result_path)

    logger.info(
        "Pruning enumeration child finished: cc_pair=%s num_docs=%s num_hierarchy_nodes=%s",
        cc_pair_id,
        len(extraction_result.raw_id_to_parent),
        len(extraction_result.hierarchy_nodes),
    )

    # os._exit skips _initializer's finally, so drain orphans here (mirrors _docfetching_task)
    reap_exited_children()
    os._exit(0)


def run_enumeration_in_subprocess(
    cc_pair_id: int,
    connector_id: int,
    credential_id: int,
    tenant_id: str,
    redis_connector: RedisConnector,
    reacquire_lock: Callable[[], object],
) -> SlimConnectorExtractionResult:
    """Spawn the enumeration child and babysit it until it produces a result.

    Raises PruneEnumerationError on child failure, stop signal, or timeout.
    """
    result_path = Path(tempfile.gettempdir()) / (
        f"onyx_prune_enum_{os.getpid()}_{cc_pair_id}_{time.monotonic_ns()}.json"
    )

    client = SimpleJobClient(n_workers=1)
    job: SimpleJob | None = client.submit(
        pruning_enumeration_task,
        str(result_path),
        cc_pair_id,
        connector_id,
        credential_id,
        tenant_id,
    )
    if job is None or job.process is None:
        raise PruneEnumerationError(
            f"Failed to spawn pruning enumeration child: cc_pair={cc_pair_id}"
        )

    logger.info(
        "Pruning enumeration child spawned: cc_pair=%s pid=%s",
        cc_pair_id,
        job.process.pid,
    )

    start = time.monotonic()
    last_lock_reacquire = start
    try:
        while True:
            job.process.join(timeout=_WATCHDOG_POLL_SECONDS)
            if not job.process.is_alive():
                break

            now = time.monotonic()

            if now - last_lock_reacquire >= _LOCK_REACQUIRE_INTERVAL_SECONDS:
                reacquire_lock()
                last_lock_reacquire = now

            if redis_connector.stop.fenced:
                raise PruneEnumerationError(
                    f"Pruning enumeration stopped by signal: cc_pair={cc_pair_id}"
                )

            # celery time limits don't work with thread pools, so the watchdog
            # is the timeout enforcement
            if now - start > JOB_TIMEOUT:
                raise PruneEnumerationError(
                    f"Pruning enumeration timed out: cc_pair={cc_pair_id} "
                    f"timeout={JOB_TIMEOUT}s"
                )

        if job.process.exitcode == 0 and result_path.exists():
            return SlimConnectorExtractionResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )

        raise PruneEnumerationError(
            f"Pruning enumeration child failed: cc_pair={cc_pair_id} "
            f"exit_code={job.process.exitcode} exception={job.exception()}"
        )
    finally:
        # never leave a live child behind, even if the watchdog itself raised
        job.terminate_and_wait(_TERMINATE_GRACE_SECONDS)
        result_path.unlink(missing_ok=True)
        Path(f"{result_path}.tmp").unlink(missing_ok=True)
