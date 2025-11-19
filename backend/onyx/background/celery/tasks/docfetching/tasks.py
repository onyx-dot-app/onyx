import multiprocessing
import os
import time
import traceback
from time import sleep

import sentry_sdk
from celery import Celery
from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.memory_monitoring import emit_process_memory
from onyx.background.celery.tasks.docprocessing.heartbeat import start_heartbeat
from onyx.background.celery.tasks.docprocessing.heartbeat import stop_heartbeat
from onyx.background.celery.tasks.docprocessing.tasks import ConnectorIndexingLogBuilder
from onyx.background.celery.tasks.docprocessing.utils import IndexingCallback
from onyx.background.celery.tasks.models import DocProcessingContext
from onyx.background.celery.tasks.models import IndexingWatchdogTerminalStatus
from onyx.background.celery.tasks.models import SimpleJobResult
from onyx.background.indexing.job_client import SimpleJob
from onyx.background.indexing.job_client import SimpleJobClient
from onyx.background.indexing.job_client import SimpleJobException
from onyx.background.indexing.run_docfetching import run_docfetching_entrypoint
from onyx.configs.constants import CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.redis.redis_connector import RedisConnector
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import SENTRY_DSN

logger = setup_logger()


def _verify_indexing_attempt(
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
) -> None:
    """
    Verify that the indexing attempt exists and is in the correct state.
    """

    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(db_session, index_attempt_id)

        if not attempt:
            raise SimpleJobException(
                f"docfetching_task - IndexAttempt not found: attempt_id={index_attempt_id}",
                code=IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND.code,
            )

        if attempt.connector_credential_pair_id != cc_pair_id:
            raise SimpleJobException(
                f"docfetching_task - CC pair mismatch: "
                f"expected={cc_pair_id} actual={attempt.connector_credential_pair_id}",
                code=IndexingWatchdogTerminalStatus.FENCE_MISMATCH.code,
            )

        if attempt.search_settings_id != search_settings_id:
            raise SimpleJobException(
                f"docfetching_task - Search settings mismatch: "
                f"expected={search_settings_id} actual={attempt.search_settings_id}",
                code=IndexingWatchdogTerminalStatus.FENCE_MISMATCH.code,
            )

        if attempt.status not in [
            IndexingStatus.NOT_STARTED,
            IndexingStatus.IN_PROGRESS,
        ]:
            raise SimpleJobException(
                f"docfetching_task - Invalid attempt status: "
                f"attempt_id={index_attempt_id} status={attempt.status}",
                code=IndexingWatchdogTerminalStatus.FENCE_MISMATCH.code,
            )

        # Check for cancellation
        if IndexingCoordination.check_cancellation_requested(
            db_session, index_attempt_id
        ):
            raise SimpleJobException(
                f"docfetching_task - Cancellation requested: attempt_id={index_attempt_id}",
                code=IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL.code,
            )

    logger.info(
        f"docfetching_task - IndexAttempt verified: "
        f"attempt_id={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )


def docfetching_task(
    app: Celery,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    is_ee: bool,
    tenant_id: str,
) -> None:
    """
    This function is run in a SimpleJob as a new process. It is responsible for validating
    some stuff, but basically it just calls run_indexing_entrypoint.

    NOTE: if an exception is raised out of this task, the primary worker will detect
    that the task transitioned to a "READY" state but the generator_complete_key doesn't exist.
    This will cause the primary worker to abort the indexing attempt and clean up.
    """

    # Start heartbeat for this indexing attempt
    heartbeat_thread, stop_event = start_heartbeat(index_attempt_id)
    try:
        _docfetching_task(
            app, index_attempt_id, cc_pair_id, search_settings_id, is_ee, tenant_id
        )
    finally:
        stop_heartbeat(heartbeat_thread, stop_event)  # Stop heartbeat before exiting


def _docfetching_task(
    app: Celery,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    is_ee: bool,
    tenant_id: str,
) -> None:
    # Since connector_indexing_proxy_task spawns a new process using this function as
    # the entrypoint, we init Sentry here.
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.1,
        )
        logger.info("Sentry initialized")
    else:
        logger.debug("Sentry DSN not provided, skipping Sentry initialization")

    logger.info(
        f"Indexing spawned task starting: "
        f"attempt={index_attempt_id} "
        f"tenant={tenant_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    # TODO: remove all fences, cause all signals to be set in postgres
    if redis_connector.delete.fenced:
        raise SimpleJobException(
            f"Indexing will not start because connector deletion is in progress: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.delete.fence_key}",
            code=IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION.code,
        )

    if redis_connector.stop.fenced:
        raise SimpleJobException(
            f"Indexing will not start because a connector stop signal was detected: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.stop.fence_key}",
            code=IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL.code,
        )

    # Verify the indexing attempt exists and is valid
    # This replaces the Redis fence payload waiting
    _verify_indexing_attempt(index_attempt_id, cc_pair_id, search_settings_id)

    try:
        with get_session_with_current_tenant() as db_session:
            attempt = get_index_attempt(db_session, index_attempt_id)
            if not attempt:
                raise SimpleJobException(
                    f"Index attempt not found: index_attempt={index_attempt_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            if not cc_pair:
                raise SimpleJobException(
                    f"cc_pair not found: cc_pair={cc_pair_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

        # define a callback class
        callback = IndexingCallback(
            redis_connector,
        )

        logger.info(
            f"Indexing spawned task running entrypoint: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # This is where the heavy/real work happens
        run_docfetching_entrypoint(
            app,
            index_attempt_id,
            tenant_id,
            cc_pair_id,
            is_ee,
            callback=callback,
        )

    except ConnectorValidationError:
        raise SimpleJobException(
            f"Indexing task failed: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}",
            code=IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR.code,
        )

    except Exception as e:
        logger.exception(
            f"Indexing spawned task failed: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # special bulletproofing ... truncate long exception messages
        # for exception types that require more args, this will fail
        # thus the try/except
        try:
            sanitized_e = type(e)(str(e)[:1024])
            sanitized_e.__traceback__ = e.__traceback__
            raise sanitized_e
        except Exception:
            raise e

    logger.info(
        f"Indexing spawned task finished: attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )
    os._exit(0)  # ensure process exits cleanly


def process_job_result(
    job: SimpleJob,
    connector_source: str | None,
    index_attempt_id: int,
    log_builder: ConnectorIndexingLogBuilder,
) -> SimpleJobResult:
    result = SimpleJobResult()
    result.connector_source = connector_source

    if job.process:
        result.exit_code = job.process.exitcode

    if job.status != "error":
        result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
        return result

    ignore_exitcode = False

    # In EKS, there is an edge case where successful tasks return exit
    # code 1 in the cloud due to the set_spawn_method not sticking.
    # Workaround: check that the total number of batches is set, since this only
    # happens when docfetching completed successfully
    with get_session_with_current_tenant() as db_session:
        index_attempt = get_index_attempt(db_session, index_attempt_id)
        if index_attempt and index_attempt.total_batches is not None:
            ignore_exitcode = True

    if ignore_exitcode:
        result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
        task_logger.warning(
            log_builder.build(
                "Indexing watchdog - spawned task has non-zero exit code "
                "but completion signal is OK. Continuing...",
                exit_code=str(result.exit_code),
            )
        )
    else:
        if result.exit_code is not None:
            result.status = IndexingWatchdogTerminalStatus.from_code(result.exit_code)

        job_level_exception = job.exception()
        result.exception_str = (
            f"Docfetching returned exit code {result.exit_code} "
            f"with exception: {job_level_exception}"
        )

    return result


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
    bind=True,
    acks_late=False,
    track_started=True,
)
def docfetching_proxy_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str,
) -> None:
    """
    This task is the entrypoint for the full indexing pipeline, which is composed of two tasks:
    docfetching and docprocessing.
    This task is spawned by "try_creating_indexing_task" which is called in the "check_for_indexing" task.

    This task spawns a new process for a new scheduled index attempt. That
    new process (which runs the docfetching_task function) does the following:

    1)  determines parameters of the indexing attempt (which connector indexing function to run,
        start and end time, from prev checkpoint or not), then run that connector. Specifically,
        connectors are responsible for reading data from an outside source and converting it to Onyx documents.
        At the moment these two steps (reading external data and converting to an Onyx document)
        are not parallelized in most connectors; that's a subject for future work.

    Each document batch produced by step 1 is stored in the file store, and a docprocessing task is spawned
    to process it. docprocessing involves the steps listed below.

    2) upserts documents to postgres (index_doc_batch_prepare)
    3) chunks each document (optionally adds context for contextual rag)
    4) embeds chunks (embed_chunks_with_failure_handling) via a call to the model server
    5) write chunks to vespa (write_chunks_to_vector_db_with_backoff)
    6) update document and indexing metadata in postgres
    7) pulls all document IDs from the source and compares those IDs to locally stored documents and deletes
    all locally stored IDs missing from the most recently pulled document ID list

    Some important notes:
    Invariants:
    - docfetching proxy tasks are spawned by check_for_indexing. The proxy then runs the docfetching_task wrapped in a watchdog.
      The watchdog is responsible for monitoring the docfetching_task and marking the index attempt as failed
      if it is not making progress.
    - All docprocessing tasks are spawned by a docfetching task.
    - all docfetching tasks, docprocessing tasks, and document batches in the file store are
      associated with a specific index attempt.
    - the index attempt status is the source of truth for what is currently happening with the index attempt.
      It is coupled with the creation/running of docfetching and docprocessing tasks as much as possible.

    How we deal with failures/ partial indexing:
    - non-checkpointed connectors/ new runs in general => delete the old document batches from the file store and do the new run
    - checkpointed connectors + resuming from checkpoint => reissue the old document batches and do a new run

    Misc:
    - most inter-process communication is handled in postgres, some is still in redis and we're trying to remove it
    - Heartbeat spawned in docfetching and docprocessing is how check_for_indexing monitors liveliness
    - progress based liveliness check: if nothing is done in 3-6 hours, mark the attempt as failed
    - TODO: task level timeouts (i.e. a connector stuck in an infinite loop)


    Comments below are from the old version and some may no longer be valid.
    TODO(rkuo): refactor this so that there is a single return path where we canonically
    log the result of running this function.

    Some more Richard notes:
    celery out of process task execution strategy is pool=prefork, but it uses fork,
    and forking is inherently unstable.

    To work around this, we use pool=threads and proxy our work to a spawned task.

    acks_late must be set to False. Otherwise, celery's visibility timeout will
    cause any task that runs longer than the timeout to be redispatched by the broker.
    There appears to be no good workaround for this, so we need to handle redispatching
    manually.
    NOTE: we try/except all db access in this function because as a watchdog, this function
    needs to be extremely stable.
    """
    # TODO: remove dependence on Redis
    start = time.monotonic()

    result = SimpleJobResult()

    ctx = DocProcessingContext(
        tenant_id=tenant_id,
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        index_attempt_id=index_attempt_id,
    )

    log_builder = ConnectorIndexingLogBuilder(ctx)

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - starting",
            mp_start_method=str(multiprocessing.get_start_method()),
        )
    )

    if not self.request.id:
        task_logger.error("self.request.id is None!")

    client = SimpleJobClient()
    task_logger.info(f"submitting docfetching_task with tenant_id={tenant_id}")

    job = client.submit(
        docfetching_task,
        self.app,
        index_attempt_id,
        cc_pair_id,
        search_settings_id,
        global_version.is_ee_version(),
        tenant_id,
    )

    if not job or not job.process:
        result.status = IndexingWatchdogTerminalStatus.SPAWN_FAILED
        task_logger.info(
            log_builder.build(
                "Indexing watchdog - finished",
                status=str(result.status.value),
                exit_code=str(result.exit_code),
            )
        )
        return

    # Ensure the process has moved out of the starting state
    num_waits = 0
    while True:
        if num_waits > 15:
            result.status = IndexingWatchdogTerminalStatus.SPAWN_NOT_ALIVE
            task_logger.info(
                log_builder.build(
                    "Indexing watchdog - finished",
                    status=str(result.status.value),
                    exit_code=str(result.exit_code),
                )
            )
            job.release()
            return

        if job.process.is_alive() or job.process.exitcode is not None:
            break

        sleep(1)
        num_waits += 1

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - spawn succeeded",
            pid=str(job.process.pid),
        )
    )

    # Track the last time memory info was emitted
    last_memory_emit_time = 0.0

    try:
        with get_session_with_current_tenant() as db_session:
            index_attempt = get_index_attempt(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                eager_load_cc_pair=True,
            )
            if not index_attempt:
                raise RuntimeError("Index attempt not found")

            result.connector_source = (
                index_attempt.connector_credential_pair.connector.source.value
            )

        while True:
            sleep(5)

            time.monotonic()

            # if the job is done, clean up and break
            if job.done():
                try:
                    result = process_job_result(
                        job, result.connector_source, index_attempt_id, log_builder
                    )
                except Exception:
                    task_logger.exception(
                        log_builder.build(
                            "Indexing watchdog - spawned task exceptioned"
                        )
                    )
                finally:
                    job.release()
                    break

            # log the memory usage for tracking down memory leaks / connector-specific memory issues
            pid = job.process.pid
            if pid is not None:
                # Only emit memory info once per minute (60 seconds)
                current_time = time.monotonic()
                if current_time - last_memory_emit_time >= 60.0:
                    emit_process_memory(
                        pid,
                        "indexing_worker",
                        {
                            "cc_pair_id": cc_pair_id,
                            "search_settings_id": search_settings_id,
                            "index_attempt_id": index_attempt_id,
                        },
                    )
                    last_memory_emit_time = current_time

            # if the spawned task is still running, restart the check once again
            # if the index attempt is not in a finished status
            try:
                with get_session_with_current_tenant() as db_session:
                    index_attempt = get_index_attempt(
                        db_session=db_session, index_attempt_id=index_attempt_id
                    )

                    if not index_attempt:
                        continue

                    if not index_attempt.is_finished():
                        continue

            except Exception:
                task_logger.exception(
                    log_builder.build(
                        "Indexing watchdog - transient exception looking up index attempt"
                    )
                )
                continue

    except Exception as e:
        result.status = IndexingWatchdogTerminalStatus.WATCHDOG_EXCEPTIONED
        if isinstance(e, ConnectorValidationError):
            # No need to expose full stack trace for validation errors
            result.exception_str = str(e)
        else:
            result.exception_str = traceback.format_exc()

    # handle exit and reporting
    elapsed = time.monotonic() - start
    if result.exception_str is not None:
        # print with exception
        try:
            with get_session_with_current_tenant() as db_session:
                attempt = get_index_attempt(db_session, ctx.index_attempt_id)

                # only mark failures if not already terminal,
                # otherwise we're overwriting potential real stack traces
                if attempt and not attempt.status.is_terminal():
                    failure_reason = (
                        f"Spawned task exceptioned: exit_code={result.exit_code}"
                    )
                    mark_attempt_failed(
                        ctx.index_attempt_id,
                        db_session,
                        failure_reason=failure_reason,
                        full_exception_trace=result.exception_str,
                    )
        except Exception:
            task_logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as failed"
                )
            )

        normalized_exception_str = "None"
        if result.exception_str:
            normalized_exception_str = result.exception_str.replace(
                "\n", "\\n"
            ).replace('"', '\\"')

        task_logger.warning(
            log_builder.build(
                "Indexing watchdog - finished",
                source=result.connector_source,
                status=result.status.value,
                exit_code=str(result.exit_code),
                exception=f'"{normalized_exception_str}"',
                elapsed=f"{elapsed:.2f}s",
            )
        )
        raise RuntimeError(f"Exception encountered: traceback={result.exception_str}")

    # print without exception
    if result.status == IndexingWatchdogTerminalStatus.TERMINATED_BY_SIGNAL:
        try:
            with get_session_with_current_tenant() as db_session:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to termination signal"
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session,
                    "Connector termination signal detected",
                )
        except Exception:
            task_logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as canceled"
                )
            )

        job.cancel()
    elif result.status == IndexingWatchdogTerminalStatus.TERMINATED_BY_ACTIVITY_TIMEOUT:
        try:
            with get_session_with_current_tenant() as db_session:
                mark_attempt_failed(
                    index_attempt_id,
                    db_session,
                    "Indexing watchdog - activity timeout exceeded: "
                    f"attempt={index_attempt_id} "
                    f"timeout={CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT}s",
                )
        except Exception:
            logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as failed"
                )
            )
        job.cancel()
    else:
        pass

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - finished",
            source=result.connector_source,
            status=str(result.status.value),
            exit_code=str(result.exit_code),
            elapsed=f"{elapsed:.2f}s",
        )
    )
