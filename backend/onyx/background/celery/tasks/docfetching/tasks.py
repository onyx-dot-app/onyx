import time
import traceback
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.background.indexing.checkpointing_utils import get_latest_valid_checkpoint
from onyx.background.indexing.checkpointing_utils import save_checkpoint
from onyx.background.indexing.run_indexing import _check_connector_and_attempt_status
from onyx.background.indexing.run_indexing import _get_connector_runner
from onyx.background.indexing.run_indexing import RunIndexingContext
from onyx.background.indexing.run_indexing import strip_null_characters
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import INDEXING_SIZE_WARNING_THRESHOLD
from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import TextSection
from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_recent_completed_attempts_for_cc_pair
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import transition_attempt_to_in_progress
from onyx.file_store.document_batch_storage import get_document_batch_storage
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _check_failure_threshold(
    total_failures: int,
    document_count: int,
    batch_num: int,
    last_failure: ConnectorFailure | None,
) -> None:
    """Check if we've hit the failure threshold and raise an appropriate exception if so.

    We consider the threshold hit if:
    1. We have more than 3 failures AND
    2. Failures account for more than 10% of processed documents
    """
    failure_ratio = total_failures / (document_count or 1)

    FAILURE_THRESHOLD = 3
    FAILURE_RATIO_THRESHOLD = 0.1
    if total_failures > FAILURE_THRESHOLD and failure_ratio > FAILURE_RATIO_THRESHOLD:
        logger.error(
            f"Connector run failed with '{total_failures}' errors "
            f"after '{batch_num}' batches."
        )
        if last_failure and last_failure.exception:
            raise last_failure.exception from last_failure.exception

        raise RuntimeError(
            f"Connector run encountered too many errors, aborting. "
            f"Last error: {last_failure}"
        )


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_DOCUMENT_EXTRACTION_TASK,
    bind=True,
    acks_late=False,
    track_started=True,
)
def connector_document_extraction_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str,
) -> None:
    """Extract documents from connector and queue them for indexing pipeline processing.

    This is the first part of the split indexing process that runs the connector
    and extracts documents, storing them in local files or S3 for later processing.
    """

    start_time = time.monotonic()

    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Document extraction starting: "
        f"attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"tenant={tenant_id}"
    )

    batch_storage = get_document_batch_storage(tenant_id, index_attempt_id)

    # Transition the index attempt from NOT_STARTED to IN_PROGRESS
    with get_session_with_current_tenant() as db_session:
        transition_attempt_to_in_progress(index_attempt_id, db_session)

    # comes from _run_indexing
    try:
        with get_session_with_current_tenant() as db_session:
            index_attempt = get_index_attempt(
                db_session,
                index_attempt_id,
                eager_load_cc_pair=True,
                eager_load_search_settings=True,
            )
            if not index_attempt:
                raise RuntimeError(f"Index attempt {index_attempt_id} not found")

            if index_attempt.search_settings is None:
                raise ValueError("Search settings must be set for indexing")

            db_connector = index_attempt.connector_credential_pair.connector
            db_credential = index_attempt.connector_credential_pair.credential
            ctx = RunIndexingContext(
                index_name=index_attempt.search_settings.index_name,
                cc_pair_id=cc_pair_id,
                connector_id=db_connector.id,
                credential_id=db_credential.id,
                source=db_connector.source,
                earliest_index_time=(
                    db_connector.indexing_start.timestamp()
                    if db_connector.indexing_start
                    else 0
                ),
                from_beginning=index_attempt.from_beginning,
                # Only update cc-pair status for primary index jobs
                # Secondary index syncs at the end when swapping
                is_primary=(
                    index_attempt.search_settings.status == IndexModelStatus.PRESENT
                ),
                search_settings_status=index_attempt.search_settings.status,
                doc_extraction_completed=False,
                batches_total=0,
                is_batch_processed=[],
                total_failures=0,
                net_doc_change=0,
            )

            # Set up time windows for polling
            last_successful_index_poll_range_end = (
                ctx.earliest_index_time
                if ctx.from_beginning
                else get_last_successful_attempt_poll_range_end(
                    cc_pair_id=ctx.cc_pair_id,
                    earliest_index=ctx.earliest_index_time,
                    search_settings=index_attempt.search_settings,
                    db_session=db_session,
                )
            )

            if last_successful_index_poll_range_end > POLL_CONNECTOR_OFFSET:
                window_start = datetime.fromtimestamp(
                    last_successful_index_poll_range_end, tz=timezone.utc
                ) - timedelta(minutes=POLL_CONNECTOR_OFFSET)
            else:
                # don't go into "negative" time if we've never indexed before
                window_start = datetime.fromtimestamp(0, tz=timezone.utc)

            most_recent_attempt = next(
                iter(
                    get_recent_completed_attempts_for_cc_pair(
                        cc_pair_id=ctx.cc_pair_id,
                        search_settings_id=index_attempt.search_settings_id,
                        db_session=db_session,
                        limit=1,
                    )
                ),
                None,
            )

            # if the last attempt failed, try and use the same window. This is necessary
            # to ensure correctness with checkpointing. If we don't do this, things like
            # new slack channels could be missed (since existing slack channels are
            # cached as part of the checkpoint).
            if (
                most_recent_attempt
                and most_recent_attempt.poll_range_end
                and (
                    most_recent_attempt.status == IndexingStatus.FAILED
                    or most_recent_attempt.status == IndexingStatus.CANCELED
                )
            ):
                window_end = most_recent_attempt.poll_range_end
            else:
                window_end = datetime.now(tz=timezone.utc)

            # TODO: do we need this?
            # # Initialize extraction state
            # state = {
            #     "connector_id": ctx.connector_id,
            #     "credential_id": ctx.credential_id,
            #     "source": ctx.source.value,
            #     "ignore_time_skip": (
            #         ctx.from_beginning
            #         or (ctx.search_settings_status == IndexModelStatus.FUTURE)
            #     ),
            #     "total_docs_processed": 0,
            #     "total_chunks_created": 0,
            #     "total_failures": 0,
            #     "net_doc_change": 0,
            #     "batches_processed": 0,
            #     "batches_total": 0,  # Will be updated as we discover more batches
            # }
            batch_storage.store_extraction_state(ctx)

            # TODO: maybe memory tracer here

            # Set up connector runner
            connector_runner = _get_connector_runner(
                db_session=db_session,
                attempt=index_attempt,
                batch_size=INDEX_BATCH_SIZE,
                start_time=window_start,
                end_time=window_end,
            )

            # don't use a checkpoint if we're explicitly indexing from
            # the beginning in order to avoid weird interactions between
            # checkpointing / failure handling
            # OR
            # if the last attempt was successful
            if index_attempt.from_beginning or (
                most_recent_attempt and most_recent_attempt.status.is_successful()
            ):
                checkpoint = connector_runner.connector.build_dummy_checkpoint()
            else:
                checkpoint = get_latest_valid_checkpoint(
                    db_session=db_session,
                    cc_pair_id=ctx.cc_pair_id,
                    search_settings_id=index_attempt.search_settings_id,
                    window_start=window_start,
                    window_end=window_end,
                    connector=connector_runner.connector,
                )

            # Save initial checkpoint
            save_checkpoint(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                checkpoint=checkpoint,
            )

        batch_num = 0
        total_doc_batches_queued = 0
        total_failures = 0
        document_count = 0

        # Main extraction loop
        while checkpoint.has_more:
            task_logger.info(
                f"Running '{ctx.source.value}' connector with checkpoint: {checkpoint}"
            )
            for document_batch, failure, next_checkpoint in connector_runner.run(
                checkpoint
            ):
                # will exception if the connector/index attempt is marked as paused/failed
                with get_session_with_current_tenant() as db_session:
                    _check_connector_and_attempt_status(
                        db_session, ctx, index_attempt_id
                    )

                # save record of any failures at the connector level
                if failure is not None:
                    total_failures += 1
                    with get_session_with_current_tenant() as db_session:
                        create_index_attempt_error(
                            index_attempt_id,
                            ctx.cc_pair_id,
                            failure,
                            db_session,
                        )

                    _check_failure_threshold(
                        total_failures, document_count, batch_num, failure
                    )

                # Save checkpoint if provided
                if next_checkpoint:
                    checkpoint = next_checkpoint

                # below is all document processing task, so if no batch we can just continue
                if document_batch is None:
                    continue

                # Clean documents and create batch
                doc_batch_cleaned = strip_null_characters(document_batch)
                batch_description = []

                for doc in doc_batch_cleaned:
                    batch_description.append(doc.to_short_descriptor())

                    doc_size = 0
                    for section in doc.sections:
                        if (
                            isinstance(section, TextSection)
                            and section.text is not None
                        ):
                            doc_size += len(section.text)

                    if doc_size > INDEXING_SIZE_WARNING_THRESHOLD:
                        logger.warning(
                            f"Document size: doc='{doc.to_short_descriptor()}' "
                            f"size={doc_size} "
                            f"threshold={INDEXING_SIZE_WARNING_THRESHOLD}"
                        )

                logger.debug(f"Indexing batch of documents: {batch_description}")

                # TODO: replicate index_attempt_md from _run_indexing, store in blob storage
                # instead of that big extraction state. index_attempt_md will be the
                # persisted communication between the connector extraction task and the
                # document processing task
                batch_id = f"batch_{batch_num}"

                # Store documents in storage
                batch_storage.store_batch(batch_id, doc_batch_cleaned)

                # Create processing task data
                processing_batch_data = {
                    "batch_id": batch_id,
                    "index_attempt_id": index_attempt_id,
                    "cc_pair_id": cc_pair_id,
                    "tenant_id": tenant_id,
                    "batch_num": batch_num + 1,  # 1-indexed
                }

                # Queue document processing task
                self.app.send_task(
                    OnyxCeleryTask.DOCUMENT_INDEXING_PIPELINE_TASK,
                    kwargs=processing_batch_data,
                    queue=OnyxCeleryQueues.DOCUMENT_INDEXING_PIPELINE,
                    priority=OnyxCeleryPriority.MEDIUM,
                )

                batch_num += 1
                total_doc_batches_queued += 1

                task_logger.info(
                    f"Queued document processing batch: "
                    f"batch_id={batch_id} "
                    f"docs={len(doc_batch_cleaned)} "
                    f"attempt={index_attempt_id}"
                )

            # Check checkpoint size periodically
            CHECKPOINT_SIZE_CHECK_INTERVAL = 100
            if batch_num % CHECKPOINT_SIZE_CHECK_INTERVAL == 0:
                check_checkpoint_size(checkpoint)

            # Save latest checkpoint
            with get_session_with_current_tenant() as db_session:
                save_checkpoint(
                    db_session=db_session,
                    index_attempt_id=index_attempt_id,
                    checkpoint=checkpoint,
                )

        elapsed_time = time.monotonic() - start_time

        task_logger.info(
            f"Document extraction completed: "
            f"attempt={index_attempt_id} "
            f"batches_queued={total_doc_batches_queued} "
            f"elapsed={elapsed_time:.2f}s"
        )

        # Update final state
        final_state = batch_storage.get_extraction_state()
        if final_state:
            final_state.batches_total = total_doc_batches_queued
            final_state.doc_extraction_completed = True
            batch_storage.store_extraction_state(final_state)

        # Queue the monitoring task to handle completion checking
        self.app.send_task(
            OnyxCeleryTask.MONITOR_docfetching_COMPLETION,
            kwargs={
                "index_attempt_id": index_attempt_id,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.DOCUMENT_INDEXING_PIPELINE,
            priority=OnyxCeleryPriority.HIGH,
            countdown=10,  # Start monitoring after 10 seconds
        )

    except Exception as e:
        task_logger.exception(
            f"Document extraction failed: "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
        )

        # Clean up on failure
        try:
            batch_storage.cleanup_all_batches()
        except Exception:
            task_logger.exception(
                "Failed to clean up document batches after extraction failure"
            )

        # Mark the attempt as failed
        with get_session_with_current_tenant() as db_session:
            mark_attempt_failed(
                index_attempt_id,
                db_session,
                failure_reason=f"Document extraction failed: {str(e)}",
                full_exception_trace=traceback.format_exc(),
            )

        raise
