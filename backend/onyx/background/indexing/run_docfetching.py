import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from celery import Celery
from sqlalchemy.orm import Session

from onyx.access.access import source_should_fetch_permissions_during_indexing
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.background.indexing.checkpointing_utils import get_latest_valid_checkpoint
from onyx.background.indexing.checkpointing_utils import save_checkpoint
from onyx.background.indexing.memory_tracer import MemoryTracer
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import INDEXING_SIZE_WARNING_THRESHOLD
from onyx.configs.app_configs import INDEXING_TRACER_INTERVAL
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.app_configs import LEAVE_CONNECTOR_ACTIVE_ON_INITIALIZATION_FAILURE
from onyx.configs.app_configs import MAX_FILE_SIZE_BYTES
from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import MilestoneRecordType
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.models import DocExtractionContext
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import TextSection
from onyx.db.connector import mark_cc_pair_as_permissions_synced
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.connector_credential_pair import update_connector_credential_pair
from onyx.db.constants import CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import get_recent_completed_attempts_for_cc_pair
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.index_attempt import transition_attempt_to_in_progress
from onyx.db.index_attempt import update_docs_indexed
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.document_batch_storage import DocumentBatchStorage
from onyx.file_store.document_batch_storage import get_document_batch_storage
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.utils.logger import setup_logger
from onyx.utils.middleware import make_randomized_onyx_request_id
from onyx.utils.telemetry import create_milestone_and_report
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import INDEX_ATTEMPT_INFO_CONTEXTVAR

logger = setup_logger(propagate=False)

INDEXING_TRACER_NUM_PRINT_ENTRIES = 5


def _get_connector_runner(
    db_session: Session,
    attempt: IndexAttempt,
    batch_size: int,
    start_time: datetime,
    end_time: datetime,
    include_permissions: bool,
    leave_connector_active: bool = LEAVE_CONNECTOR_ACTIVE_ON_INITIALIZATION_FAILURE,
) -> ConnectorRunner:
    """
    NOTE: `start_time` and `end_time` are only used for poll connectors

    Returns an iterator of document batches and whether the returned documents
    are the complete list of existing documents of the connector. If the task
    of type LOAD_STATE, the list will be considered complete and otherwise incomplete.
    """

    task = attempt.connector_credential_pair.connector.input_type

    try:
        runnable_connector = instantiate_connector(
            db_session=db_session,
            source=attempt.connector_credential_pair.connector.source,
            input_type=task,
            connector_specific_config=attempt.connector_credential_pair.connector.connector_specific_config,
            credential=attempt.connector_credential_pair.credential,
        )

        # validate the connector settings
        if not INTEGRATION_TESTS_MODE:
            runnable_connector.validate_connector_settings()
            if attempt.connector_credential_pair.access_type == AccessType.SYNC:
                runnable_connector.validate_perm_sync()

    except UnexpectedValidationError as e:
        logger.exception(
            "Unable to instantiate connector due to an unexpected temporary issue."
        )
        raise e
    except Exception as e:
        logger.exception("Unable to instantiate connector. Pausing until fixed.")
        # since we failed to even instantiate the connector, we pause the CCPair since
        # it will never succeed

        # Sometimes there are cases where the connector will
        # intermittently fail to initialize in which case we should pass in
        # leave_connector_active=True to allow it to continue.
        # For example, if there is nightly maintenance on a Confluence Server instance,
        # the connector will fail to initialize every night.
        if not leave_connector_active:
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=attempt.connector_credential_pair.id,
            )
            if cc_pair and cc_pair.status == ConnectorCredentialPairStatus.ACTIVE:
                update_connector_credential_pair(
                    db_session=db_session,
                    connector_id=attempt.connector_credential_pair.connector.id,
                    credential_id=attempt.connector_credential_pair.credential.id,
                    status=ConnectorCredentialPairStatus.PAUSED,
                )
        raise e

    return ConnectorRunner(
        connector=runnable_connector,
        batch_size=batch_size,
        include_permissions=include_permissions,
        time_range=(start_time, end_time),
    )


def strip_null_characters(doc_batch: list[Document]) -> list[Document]:
    cleaned_batch = []
    for doc in doc_batch:
        if sys.getsizeof(doc) > MAX_FILE_SIZE_BYTES:
            logger.warning(
                f"doc {doc.id} too large, Document size: {sys.getsizeof(doc)}"
            )
        cleaned_doc = doc.model_copy()

        # Postgres cannot handle NUL characters in text fields
        if "\x00" in cleaned_doc.id:
            logger.warning(f"NUL characters found in document ID: {cleaned_doc.id}")
            cleaned_doc.id = cleaned_doc.id.replace("\x00", "")

        if cleaned_doc.title and "\x00" in cleaned_doc.title:
            logger.warning(
                f"NUL characters found in document title: {cleaned_doc.title}"
            )
            cleaned_doc.title = cleaned_doc.title.replace("\x00", "")

        if "\x00" in cleaned_doc.semantic_identifier:
            logger.warning(
                f"NUL characters found in document semantic identifier: {cleaned_doc.semantic_identifier}"
            )
            cleaned_doc.semantic_identifier = cleaned_doc.semantic_identifier.replace(
                "\x00", ""
            )

        for section in cleaned_doc.sections:
            if section.link is not None:
                section.link = section.link.replace("\x00", "")

            # since text can be longer, just replace to avoid double scan
            if isinstance(section, TextSection) and section.text is not None:
                section.text = section.text.replace("\x00", "")

        cleaned_batch.append(cleaned_doc)

    return cleaned_batch


def _check_connector_and_attempt_status(
    db_session_temp: Session,
    cc_pair_id: int,
    search_settings_status: IndexModelStatus,
    index_attempt_id: int,
) -> None:
    """
    Checks the status of the connector credential pair and index attempt.
    Raises a RuntimeError if any conditions are not met.
    """
    cc_pair_loop = get_connector_credential_pair_from_id(
        db_session_temp,
        cc_pair_id,
    )
    if not cc_pair_loop:
        raise RuntimeError(f"CC pair {cc_pair_id} not found in DB.")

    if (
        cc_pair_loop.status == ConnectorCredentialPairStatus.PAUSED
        and search_settings_status != IndexModelStatus.FUTURE
    ) or cc_pair_loop.status == ConnectorCredentialPairStatus.DELETING:
        raise ConnectorStopSignal(f"Connector {cc_pair_loop.status.value.lower()}")

    index_attempt_loop = get_index_attempt(db_session_temp, index_attempt_id)
    if not index_attempt_loop:
        raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")

    if index_attempt_loop.status == IndexingStatus.CANCELED:
        raise ConnectorStopSignal(f"Index attempt {index_attempt_id} was canceled")

    if index_attempt_loop.status != IndexingStatus.IN_PROGRESS:
        error_str = ""
        if index_attempt_loop.error_msg:
            error_str = f" Original error: {index_attempt_loop.error_msg}"

        raise RuntimeError(
            f"Index Attempt is not running, status is {index_attempt_loop.status}.{error_str}"
        )

    if index_attempt_loop.celery_task_id is None:
        raise RuntimeError(f"Index attempt {index_attempt_id} has no celery task id")


# TODO: delete from here if ends up unused
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


# NOTE: this is the old run_indexing function that the new decoupled approach
# is based on. Leaving this for comparison purposes, but if you see this comment
# has been here for >2 month, please delete this function.
def _run_indexing(
    db_session: Session,
    index_attempt_id: int,
    tenant_id: str,
    callback: IndexingHeartbeatInterface | None = None,
) -> None:
    """
    1. Get documents which are either new or updated from specified application
    2. Embed and index these documents into the chosen datastore (vespa)
    3. Updates Postgres to record the indexed documents + the outcome of this run
    """
    from onyx.indexing.indexing_pipeline import run_indexing_pipeline

    start_time = time.monotonic()  # jsut used for logging

    with get_session_with_current_tenant() as db_session_temp:
        index_attempt_start = get_index_attempt(
            db_session_temp,
            index_attempt_id,
            eager_load_cc_pair=True,
            eager_load_search_settings=True,
        )
        if not index_attempt_start:
            raise ValueError(
                f"Index attempt {index_attempt_id} does not exist in DB. This should not be possible."
            )

        if index_attempt_start.search_settings is None:
            raise ValueError(
                "Search settings must be set for indexing. This should not be possible."
            )

        db_connector = index_attempt_start.connector_credential_pair.connector
        db_credential = index_attempt_start.connector_credential_pair.credential
        is_primary = (
            index_attempt_start.search_settings.status == IndexModelStatus.PRESENT
        )
        from_beginning = index_attempt_start.from_beginning
        has_successful_attempt = (
            index_attempt_start.connector_credential_pair.last_successful_index_time
            is not None
        )
        ctx = DocExtractionContext(
            index_name=index_attempt_start.search_settings.index_name,
            cc_pair_id=index_attempt_start.connector_credential_pair.id,
            connector_id=db_connector.id,
            credential_id=db_credential.id,
            source=db_connector.source,
            earliest_index_time=(
                db_connector.indexing_start.timestamp()
                if db_connector.indexing_start
                else 0
            ),
            from_beginning=from_beginning,
            # Only update cc-pair status for primary index jobs
            # Secondary index syncs at the end when swapping
            is_primary=is_primary,
            should_fetch_permissions_during_indexing=(
                index_attempt_start.connector_credential_pair.access_type
                == AccessType.SYNC
                and source_should_fetch_permissions_during_indexing(db_connector.source)
                and is_primary
                # if we've already successfully indexed, let the doc_sync job
                # take care of doc-level permissions
                and (from_beginning or not has_successful_attempt)
            ),
            search_settings_status=index_attempt_start.search_settings.status,
            doc_extraction_complete_batch_num=None,
        )

        last_successful_index_poll_range_end = (
            ctx.earliest_index_time
            if ctx.from_beginning
            else get_last_successful_attempt_poll_range_end(
                cc_pair_id=ctx.cc_pair_id,
                earliest_index=ctx.earliest_index_time,
                search_settings=index_attempt_start.search_settings,
                db_session=db_session_temp,
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
                    search_settings_id=index_attempt_start.search_settings_id,
                    db_session=db_session_temp,
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

        # add start/end now that they have been set
        index_attempt_start.poll_range_start = window_start
        index_attempt_start.poll_range_end = window_end
        db_session_temp.add(index_attempt_start)
        db_session_temp.commit()

        embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=index_attempt_start.search_settings,
            callback=callback,
        )

    information_content_classification_model = InformationContentClassificationModel()

    document_index = get_default_document_index(
        index_attempt_start.search_settings,
        None,
        httpx_client=HttpxPool.get("vespa"),
    )

    # Initialize memory tracer. NOTE: won't actually do anything if
    # `INDEXING_TRACER_INTERVAL` is 0.
    memory_tracer = MemoryTracer(interval=INDEXING_TRACER_INTERVAL)
    memory_tracer.start()

    index_attempt_md = IndexAttemptMetadata(
        attempt_id=index_attempt_id,
        connector_id=ctx.connector_id,
        credential_id=ctx.credential_id,
    )

    total_failures = 0
    batch_num = 0
    net_doc_change = 0
    document_count = 0
    chunk_count = 0
    index_attempt: IndexAttempt | None = None
    try:
        with get_session_with_current_tenant() as db_session_temp:
            index_attempt = get_index_attempt(
                db_session_temp, index_attempt_id, eager_load_cc_pair=True
            )
            if not index_attempt:
                raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")

            connector_runner = _get_connector_runner(
                db_session=db_session_temp,
                attempt=index_attempt,
                batch_size=INDEX_BATCH_SIZE,
                start_time=window_start,
                end_time=window_end,
                include_permissions=ctx.should_fetch_permissions_during_indexing,
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
                checkpoint, _ = get_latest_valid_checkpoint(
                    db_session=db_session_temp,
                    cc_pair_id=ctx.cc_pair_id,
                    search_settings_id=index_attempt.search_settings_id,
                    window_start=window_start,
                    window_end=window_end,
                    connector=connector_runner.connector,
                )

            # save the initial checkpoint to have a proper record of the
            # "last used checkpoint"
            save_checkpoint(
                db_session=db_session_temp,
                index_attempt_id=index_attempt_id,
                checkpoint=checkpoint,
            )

            unresolved_errors = get_index_attempt_errors_for_cc_pair(
                cc_pair_id=ctx.cc_pair_id,
                unresolved_only=True,
                db_session=db_session_temp,
            )
            doc_id_to_unresolved_errors: dict[str, list[IndexAttemptError]] = (
                defaultdict(list)
            )
            for error in unresolved_errors:
                if error.document_id:
                    doc_id_to_unresolved_errors[error.document_id].append(error)

            entity_based_unresolved_errors = [
                error for error in unresolved_errors if error.entity_id
            ]

        while checkpoint.has_more:
            logger.info(
                f"Running '{ctx.source.value}' connector with checkpoint: {checkpoint}"
            )
            for document_batch, failure, next_checkpoint in connector_runner.run(
                checkpoint
            ):
                # Check if connector is disabled mid run and stop if so unless it's the secondary
                # index being built. We want to populate it even for paused connectors
                # Often paused connectors are sources that aren't updated frequently but the
                # contents still need to be initially pulled.
                if callback:
                    if callback.should_stop():
                        raise ConnectorStopSignal("Connector stop signal detected")

                    # NOTE: this progress callback runs on every loop. We've seen cases
                    # where we loop many times with no new documents and eventually time
                    # out, so only doing the callback after indexing isn't sufficient.
                    callback.progress("_run_indexing", 0)

                # TODO: should we move this into the above callback instead?
                with get_session_with_current_tenant() as db_session_temp:
                    # will exception if the connector/index attempt is marked as paused/failed
                    _check_connector_and_attempt_status(
                        db_session_temp,
                        ctx.cc_pair_id,
                        ctx.search_settings_status,
                        index_attempt_id,
                    )

                # save record of any failures at the connector level
                if failure is not None:
                    total_failures += 1
                    with get_session_with_current_tenant() as db_session_temp:
                        create_index_attempt_error(
                            index_attempt_id,
                            ctx.cc_pair_id,
                            failure,
                            db_session_temp,
                        )

                    _check_failure_threshold(
                        total_failures, document_count, batch_num, failure
                    )

                # save the new checkpoint (if one is provided)
                if next_checkpoint:
                    checkpoint = next_checkpoint

                # below is all document processing logic, so if no batch we can just continue
                if document_batch is None:
                    continue

                batch_description = []

                # Generate an ID that can be used to correlate activity between here
                # and the embedding model server
                doc_batch_cleaned = strip_null_characters(document_batch)
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

                index_attempt_md.request_id = make_randomized_onyx_request_id("CIX")
                index_attempt_md.structured_id = (
                    f"{tenant_id}:{ctx.cc_pair_id}:{index_attempt_id}:{batch_num}"
                )
                index_attempt_md.batch_num = batch_num + 1  # use 1-index for this

                # real work happens here!
                adapter = DocumentIndexingBatchAdapter(
                    db_session=db_session,
                    connector_id=ctx.connector_id,
                    credential_id=ctx.credential_id,
                    tenant_id=tenant_id,
                    index_attempt_metadata=index_attempt_md,
                )
                index_pipeline_result = run_indexing_pipeline(
                    embedder=embedding_model,
                    information_content_classification_model=information_content_classification_model,
                    document_index=document_index,
                    ignore_time_skip=(
                        ctx.from_beginning
                        or (ctx.search_settings_status == IndexModelStatus.FUTURE)
                    ),
                    db_session=db_session,
                    tenant_id=tenant_id,
                    document_batch=doc_batch_cleaned,
                    request_id=index_attempt_md.request_id,
                    adapter=adapter,
                )

                batch_num += 1
                net_doc_change += index_pipeline_result.new_docs
                chunk_count += index_pipeline_result.total_chunks
                document_count += index_pipeline_result.total_docs

                # resolve errors for documents that were successfully indexed
                failed_document_ids = [
                    failure.failed_document.document_id
                    for failure in index_pipeline_result.failures
                    if failure.failed_document
                ]
                successful_document_ids = [
                    document.id
                    for document in document_batch
                    if document.id not in failed_document_ids
                ]
                for document_id in successful_document_ids:
                    with get_session_with_current_tenant() as db_session_temp:
                        if document_id in doc_id_to_unresolved_errors:
                            logger.info(
                                f"Resolving IndexAttemptError for document '{document_id}'"
                            )
                            for error in doc_id_to_unresolved_errors[document_id]:
                                error.is_resolved = True
                                db_session_temp.add(error)
                        db_session_temp.commit()

                # add brand new failures
                if index_pipeline_result.failures:
                    total_failures += len(index_pipeline_result.failures)
                    with get_session_with_current_tenant() as db_session_temp:
                        for failure in index_pipeline_result.failures:
                            create_index_attempt_error(
                                index_attempt_id,
                                ctx.cc_pair_id,
                                failure,
                                db_session_temp,
                            )

                    _check_failure_threshold(
                        total_failures,
                        document_count,
                        batch_num,
                        index_pipeline_result.failures[-1],
                    )

                # This new value is updated every batch, so UI can refresh per batch update
                with get_session_with_current_tenant() as db_session_temp:
                    # NOTE: Postgres uses the start of the transactions when computing `NOW()`
                    # so we need either to commit() or to use a new session
                    update_docs_indexed(
                        db_session=db_session_temp,
                        index_attempt_id=index_attempt_id,
                        total_docs_indexed=document_count,
                        new_docs_indexed=net_doc_change,
                        docs_removed_from_index=0,
                    )

                if callback:
                    callback.progress("_run_indexing", len(doc_batch_cleaned))

                # Add telemetry for indexing progress
                optional_telemetry(
                    record_type=RecordType.INDEXING_PROGRESS,
                    data={
                        "index_attempt_id": index_attempt_id,
                        "cc_pair_id": ctx.cc_pair_id,
                        "current_docs_indexed": document_count,
                        "current_chunks_indexed": chunk_count,
                        "source": ctx.source.value,
                    },
                    tenant_id=tenant_id,
                )

                memory_tracer.increment_and_maybe_trace()

            # `make sure the checkpoints aren't getting too large`at some regular interval
            CHECKPOINT_SIZE_CHECK_INTERVAL = 100
            if batch_num % CHECKPOINT_SIZE_CHECK_INTERVAL == 0:
                check_checkpoint_size(checkpoint)

            # save latest checkpoint
            with get_session_with_current_tenant() as db_session_temp:
                save_checkpoint(
                    db_session=db_session_temp,
                    index_attempt_id=index_attempt_id,
                    checkpoint=checkpoint,
                )

        optional_telemetry(
            record_type=RecordType.INDEXING_COMPLETE,
            data={
                "index_attempt_id": index_attempt_id,
                "cc_pair_id": ctx.cc_pair_id,
                "total_docs_indexed": document_count,
                "total_chunks": chunk_count,
                "time_elapsed_seconds": time.monotonic() - start_time,
                "source": ctx.source.value,
            },
            tenant_id=tenant_id,
        )

    except Exception as e:
        logger.exception(
            "Connector run exceptioned after elapsed time: "
            f"{time.monotonic() - start_time} seconds"
        )
        if isinstance(e, ConnectorValidationError):
            # On validation errors during indexing, we want to cancel the indexing attempt
            # and mark the CCPair as invalid. This prevents the connector from being
            # used in the future until the credentials are updated.
            with get_session_with_current_tenant() as db_session_temp:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to validation error."
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session_temp,
                    reason=f"{CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX}{str(e)}",
                )

                if ctx.is_primary:
                    if not index_attempt:
                        # should always be set by now
                        raise RuntimeError("Should never happen.")

                    VALIDATION_ERROR_THRESHOLD = 5

                    recent_index_attempts = get_recent_completed_attempts_for_cc_pair(
                        cc_pair_id=ctx.cc_pair_id,
                        search_settings_id=index_attempt.search_settings_id,
                        limit=VALIDATION_ERROR_THRESHOLD,
                        db_session=db_session_temp,
                    )
                    num_validation_errors = len(
                        [
                            index_attempt
                            for index_attempt in recent_index_attempts
                            if index_attempt.error_msg
                            and index_attempt.error_msg.startswith(
                                CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX
                            )
                        ]
                    )

                    if num_validation_errors >= VALIDATION_ERROR_THRESHOLD:
                        logger.warning(
                            f"Connector {ctx.connector_id} has {num_validation_errors} consecutive validation"
                            f" errors. Marking the CC Pair as invalid."
                        )
                        update_connector_credential_pair(
                            db_session=db_session_temp,
                            connector_id=ctx.connector_id,
                            credential_id=ctx.credential_id,
                            status=ConnectorCredentialPairStatus.INVALID,
                        )
            memory_tracer.stop()
            raise e

        elif isinstance(e, ConnectorStopSignal):
            with get_session_with_current_tenant() as db_session_temp:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to stop signal."
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session_temp,
                    reason=str(e),
                )

                if ctx.is_primary:
                    update_connector_credential_pair(
                        db_session=db_session_temp,
                        connector_id=ctx.connector_id,
                        credential_id=ctx.credential_id,
                        net_docs=net_doc_change,
                    )

            memory_tracer.stop()
            raise e
        else:
            with get_session_with_current_tenant() as db_session_temp:
                mark_attempt_failed(
                    index_attempt_id,
                    db_session_temp,
                    failure_reason=str(e),
                    full_exception_trace=traceback.format_exc(),
                )

                if ctx.is_primary:
                    update_connector_credential_pair(
                        db_session=db_session_temp,
                        connector_id=ctx.connector_id,
                        credential_id=ctx.credential_id,
                        net_docs=net_doc_change,
                    )

            memory_tracer.stop()
            raise e

    memory_tracer.stop()

    # we know index attempt is successful (at least partially) at this point,
    # all other cases have been short-circuited
    elapsed_time = time.monotonic() - start_time
    with get_session_with_current_tenant() as db_session_temp:
        # resolve entity-based errors
        for error in entity_based_unresolved_errors:
            logger.info(f"Resolving IndexAttemptError for entity '{error.entity_id}'")
            error.is_resolved = True
            db_session_temp.add(error)
            db_session_temp.commit()

        if total_failures == 0:
            mark_attempt_succeeded(index_attempt_id, db_session_temp)

            create_milestone_and_report(
                user=None,
                distinct_id=tenant_id or "N/A",
                event_type=MilestoneRecordType.CONNECTOR_SUCCEEDED,
                properties=None,
                db_session=db_session_temp,
            )

            logger.info(
                f"Connector succeeded: "
                f"docs={document_count} chunks={chunk_count} elapsed={elapsed_time:.2f}s"
            )

        else:
            mark_attempt_partially_succeeded(index_attempt_id, db_session_temp)
            logger.info(
                f"Connector completed with some errors: "
                f"failures={total_failures} "
                f"batches={batch_num} "
                f"docs={document_count} "
                f"chunks={chunk_count} "
                f"elapsed={elapsed_time:.2f}s"
            )

        if ctx.is_primary:
            update_connector_credential_pair(
                db_session=db_session_temp,
                connector_id=ctx.connector_id,
                credential_id=ctx.credential_id,
                run_dt=window_end,
            )
            if ctx.should_fetch_permissions_during_indexing:
                mark_cc_pair_as_permissions_synced(
                    db_session=db_session_temp,
                    cc_pair_id=ctx.cc_pair_id,
                    start_time=window_end,
                )


def run_docfetching_entrypoint(
    app: Celery,
    index_attempt_id: int,
    tenant_id: str,
    connector_credential_pair_id: int,
    is_ee: bool = False,
    callback: IndexingHeartbeatInterface | None = None,
) -> None:
    """Don't swallow exceptions here ... propagate them up."""

    if is_ee:
        global_version.set_ee()

    # set the indexing attempt ID so that all log messages from this process
    # will have it added as a prefix
    token = INDEX_ATTEMPT_INFO_CONTEXTVAR.set(
        (connector_credential_pair_id, index_attempt_id)
    )
    with get_session_with_current_tenant() as db_session:
        attempt = transition_attempt_to_in_progress(index_attempt_id, db_session)

        tenant_str = ""
        if MULTI_TENANT:
            tenant_str = f" for tenant {tenant_id}"

        connector_name = attempt.connector_credential_pair.connector.name
        connector_config = (
            attempt.connector_credential_pair.connector.connector_specific_config
        )
        credential_id = attempt.connector_credential_pair.credential_id

    logger.info(
        f"Docfetching starting{tenant_str}: "
        f"connector='{connector_name}' "
        f"config='{connector_config}' "
        f"credentials='{credential_id}'"
    )

    connector_document_extraction(
        app,
        index_attempt_id,
        attempt.connector_credential_pair_id,
        attempt.search_settings_id,
        tenant_id,
        callback,
    )

    logger.info(
        f"Docfetching finished{tenant_str}: "
        f"connector='{connector_name}' "
        f"config='{connector_config}' "
        f"credentials='{credential_id}'"
    )

    INDEX_ATTEMPT_INFO_CONTEXTVAR.reset(token)


def connector_document_extraction(
    app: Celery,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str,
    callback: IndexingHeartbeatInterface | None = None,
) -> None:
    """Extract documents from connector and queue them for indexing pipeline processing.

    This is the first part of the split indexing process that runs the connector
    and extracts documents, storing them in the filestore for later processing.
    """

    start_time = time.monotonic()

    logger.info(
        f"Document extraction starting: "
        f"attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"tenant={tenant_id}"
    )

    # Get batch storage (transition to IN_PROGRESS is handled by run_indexing_entrypoint)
    batch_storage = get_document_batch_storage(cc_pair_id, index_attempt_id)

    # Initialize memory tracer. NOTE: won't actually do anything if
    # `INDEXING_TRACER_INTERVAL` is 0.
    memory_tracer = MemoryTracer(interval=INDEXING_TRACER_INTERVAL)
    memory_tracer.start()

    index_attempt = None
    last_batch_num = 0  # used to continue from checkpointing
    # comes from _run_indexing
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

        # Clear the indexing trigger if it was set, to prevent duplicate indexing attempts
        if index_attempt.connector_credential_pair.indexing_trigger is not None:
            logger.info(
                "Clearing indexing trigger: "
                f"cc_pair={index_attempt.connector_credential_pair.id} "
                f"trigger={index_attempt.connector_credential_pair.indexing_trigger}"
            )
            mark_ccpair_with_indexing_trigger(
                index_attempt.connector_credential_pair.id, None, db_session
            )

        db_connector = index_attempt.connector_credential_pair.connector
        db_credential = index_attempt.connector_credential_pair.credential
        is_primary = index_attempt.search_settings.status == IndexModelStatus.PRESENT
        from_beginning = index_attempt.from_beginning
        has_successful_attempt = (
            index_attempt.connector_credential_pair.last_successful_index_time
            is not None
        )

        earliest_index_time = (
            db_connector.indexing_start.timestamp()
            if db_connector.indexing_start
            else 0
        )
        should_fetch_permissions_during_indexing = (
            index_attempt.connector_credential_pair.access_type == AccessType.SYNC
            and source_should_fetch_permissions_during_indexing(db_connector.source)
            and is_primary
            # if we've already successfully indexed, let the doc_sync job
            # take care of doc-level permissions
            and (from_beginning or not has_successful_attempt)
        )

        # Set up time windows for polling
        last_successful_index_poll_range_end = (
            earliest_index_time
            if from_beginning
            else get_last_successful_attempt_poll_range_end(
                cc_pair_id=cc_pair_id,
                earliest_index=earliest_index_time,
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
                    cc_pair_id=cc_pair_id,
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

        # set time range in db
        index_attempt.poll_range_start = window_start
        index_attempt.poll_range_end = window_end
        db_session.commit()

        # TODO: maybe memory tracer here

        # Set up connector runner
        connector_runner = _get_connector_runner(
            db_session=db_session,
            attempt=index_attempt,
            batch_size=INDEX_BATCH_SIZE,
            start_time=window_start,
            end_time=window_end,
            include_permissions=should_fetch_permissions_during_indexing,
        )

        # don't use a checkpoint if we're explicitly indexing from
        # the beginning in order to avoid weird interactions between
        # checkpointing / failure handling
        # OR
        # if the last attempt was successful
        if index_attempt.from_beginning or (
            most_recent_attempt and most_recent_attempt.status.is_successful()
        ):
            logger.info(
                f"Cleaning up all old batches for index attempt {index_attempt_id} before starting new run"
            )
            batch_storage.cleanup_all_batches()
            checkpoint = connector_runner.connector.build_dummy_checkpoint()
        else:
            logger.info(
                f"Getting latest valid checkpoint for index attempt {index_attempt_id}"
            )
            checkpoint, resuming_from_checkpoint = get_latest_valid_checkpoint(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
                search_settings_id=index_attempt.search_settings_id,
                window_start=window_start,
                window_end=window_end,
                connector=connector_runner.connector,
            )

            # checkpoint resumption OR the connector already finished.
            if (
                isinstance(connector_runner.connector, CheckpointedConnector)
                and resuming_from_checkpoint
            ) or (
                most_recent_attempt
                and most_recent_attempt.total_batches is not None
                and not checkpoint.has_more
            ):
                reissued_batch_count, completed_batches = reissue_old_batches(
                    batch_storage,
                    index_attempt_id,
                    cc_pair_id,
                    tenant_id,
                    app,
                    most_recent_attempt,
                )
                last_batch_num = reissued_batch_count + completed_batches
                index_attempt.completed_batches = completed_batches
                db_session.commit()
            else:
                logger.info(
                    f"Cleaning up all batches for index attempt {index_attempt_id} before starting new run"
                )
                # for non-checkpointed connectors, throw out batches from previous unsuccessful attempts
                # because we'll be getting those documents again anyways.
                batch_storage.cleanup_all_batches()

        # Save initial checkpoint
        save_checkpoint(
            db_session=db_session,
            index_attempt_id=index_attempt_id,
            checkpoint=checkpoint,
        )

    try:
        batch_num = last_batch_num  # starts at 0 if no last batch
        total_doc_batches_queued = 0
        total_failures = 0
        document_count = 0

        # Main extraction loop
        while checkpoint.has_more:
            logger.info(
                f"Running '{db_connector.source.value}' connector with checkpoint: {checkpoint}"
            )
            for document_batch, failure, next_checkpoint in connector_runner.run(
                checkpoint
            ):
                # Check if connector is disabled mid run and stop if so unless it's the secondary
                # index being built. We want to populate it even for paused connectors
                # Often paused connectors are sources that aren't updated frequently but the
                # contents still need to be initially pulled.
                if callback and callback.should_stop():
                    raise ConnectorStopSignal("Connector stop signal detected")

                # will exception if the connector/index attempt is marked as paused/failed
                with get_session_with_current_tenant() as db_session_tmp:
                    _check_connector_and_attempt_status(
                        db_session_tmp,
                        cc_pair_id,
                        index_attempt.search_settings.status,
                        index_attempt_id,
                    )

                # save record of any failures at the connector level
                if failure is not None:
                    total_failures += 1
                    with get_session_with_current_tenant() as db_session:
                        create_index_attempt_error(
                            index_attempt_id,
                            cc_pair_id,
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
                if not document_batch:
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
                memory_tracer.increment_and_maybe_trace()

                # Store documents in storage
                batch_storage.store_batch(batch_num, doc_batch_cleaned)

                # Create processing task data
                processing_batch_data = {
                    "index_attempt_id": index_attempt_id,
                    "cc_pair_id": cc_pair_id,
                    "tenant_id": tenant_id,
                    "batch_num": batch_num,  # 0-indexed
                }

                # Queue document processing task
                app.send_task(
                    OnyxCeleryTask.DOCPROCESSING_TASK,
                    kwargs=processing_batch_data,
                    queue=OnyxCeleryQueues.DOCPROCESSING,
                    priority=OnyxCeleryPriority.MEDIUM,
                )

                batch_num += 1
                total_doc_batches_queued += 1

                logger.info(
                    f"Queued document processing batch: "
                    f"batch_num={batch_num} "
                    f"docs={len(doc_batch_cleaned)} "
                    f"attempt={index_attempt_id}"
                )

            # Check checkpoint size periodically
            CHECKPOINT_SIZE_CHECK_INTERVAL = 100
            if batch_num % CHECKPOINT_SIZE_CHECK_INTERVAL == 0:
                check_checkpoint_size(checkpoint)

            # Save latest checkpoint
            # NOTE: checkpointing is used to track which batches have
            # been sent to the filestore, NOT which batches have been fully indexed
            # as it used to be.
            with get_session_with_current_tenant() as db_session:
                save_checkpoint(
                    db_session=db_session,
                    index_attempt_id=index_attempt_id,
                    checkpoint=checkpoint,
                )

        elapsed_time = time.monotonic() - start_time

        logger.info(
            f"Document extraction completed: "
            f"attempt={index_attempt_id} "
            f"batches_queued={total_doc_batches_queued} "
            f"elapsed={elapsed_time:.2f}s"
        )

        # Set total batches in database to signal extraction completion.
        # Used by check_for_indexing to determine if the index attempt is complete.
        with get_session_with_current_tenant() as db_session:
            IndexingCoordination.set_total_batches(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_batches=batch_num,
            )

    except Exception as e:
        logger.exception(
            f"Document extraction failed: "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
        )

        # Do NOT clean up batches on failure; future runs will use those batches
        # while docfetching will continue from the saved checkpoint if one exists

        if isinstance(e, ConnectorValidationError):
            # On validation errors during indexing, we want to cancel the indexing attempt
            # and mark the CCPair as invalid. This prevents the connector from being
            # used in the future until the credentials are updated.
            with get_session_with_current_tenant() as db_session_temp:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to validation error."
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session_temp,
                    reason=f"{CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX}{str(e)}",
                )

                if is_primary:
                    if not index_attempt:
                        # should always be set by now
                        raise RuntimeError("Should never happen.")

                    VALIDATION_ERROR_THRESHOLD = 5

                    recent_index_attempts = get_recent_completed_attempts_for_cc_pair(
                        cc_pair_id=cc_pair_id,
                        search_settings_id=index_attempt.search_settings_id,
                        limit=VALIDATION_ERROR_THRESHOLD,
                        db_session=db_session_temp,
                    )
                    num_validation_errors = len(
                        [
                            index_attempt
                            for index_attempt in recent_index_attempts
                            if index_attempt.error_msg
                            and index_attempt.error_msg.startswith(
                                CONNECTOR_VALIDATION_ERROR_MESSAGE_PREFIX
                            )
                        ]
                    )

                    if num_validation_errors >= VALIDATION_ERROR_THRESHOLD:
                        logger.warning(
                            f"Connector {db_connector.id} has {num_validation_errors} consecutive validation"
                            f" errors. Marking the CC Pair as invalid."
                        )
                        update_connector_credential_pair(
                            db_session=db_session_temp,
                            connector_id=db_connector.id,
                            credential_id=db_credential.id,
                            status=ConnectorCredentialPairStatus.INVALID,
                        )
            raise e
        elif isinstance(e, ConnectorStopSignal):
            with get_session_with_current_tenant() as db_session_temp:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to stop signal."
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session_temp,
                    reason=str(e),
                )

        else:
            with get_session_with_current_tenant() as db_session_temp:
                # don't overwrite attempts that are already failed/canceled for another reason
                index_attempt = get_index_attempt(db_session_temp, index_attempt_id)
                if index_attempt and index_attempt.status in [
                    IndexingStatus.CANCELED,
                    IndexingStatus.FAILED,
                ]:
                    logger.info(
                        f"Attempt {index_attempt_id} is already failed/canceled, skipping marking as failed."
                    )
                    raise e

                mark_attempt_failed(
                    index_attempt_id,
                    db_session_temp,
                    failure_reason=str(e),
                    full_exception_trace=traceback.format_exc(),
                )

            raise e

    finally:
        memory_tracer.stop()


def reissue_old_batches(
    batch_storage: DocumentBatchStorage,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    app: Celery,
    most_recent_attempt: IndexAttempt | None,
) -> tuple[int, int]:
    # When loading from a checkpoint, we need to start new docprocessing tasks
    # tied to the new index attempt for any batches left over in the file store
    old_batches = batch_storage.get_all_batches_for_cc_pair()
    batch_storage.update_old_batches_to_new_index_attempt(old_batches)
    for batch_id in old_batches:
        logger.info(
            f"Re-issuing docprocessing task for batch {batch_id} for index attempt {index_attempt_id}"
        )
        path_info = batch_storage.extract_path_info(batch_id)
        if path_info is None:
            logger.warning(
                f"Could not extract path info from batch {batch_id}, skipping"
            )
            continue
        if path_info.cc_pair_id != cc_pair_id:
            raise RuntimeError(f"Batch {batch_id} is not for cc pair {cc_pair_id}")

        app.send_task(
            OnyxCeleryTask.DOCPROCESSING_TASK,
            kwargs={
                "index_attempt_id": index_attempt_id,
                "cc_pair_id": cc_pair_id,
                "tenant_id": tenant_id,
                "batch_num": path_info.batch_num,  # use same batch num as previously
            },
            queue=OnyxCeleryQueues.DOCPROCESSING,
            priority=OnyxCeleryPriority.MEDIUM,
        )
    recent_batches = most_recent_attempt.completed_batches if most_recent_attempt else 0
    # resume from the batch num of the last attempt. This should be one more
    # than the last batch created by docfetching regardless of whether the batch
    # is still in the filestore waiting for processing or not.
    last_batch_num = len(old_batches) + recent_batches
    logger.info(
        f"Starting from batch {last_batch_num} due to "
        f"re-issued batches: {old_batches}, completed batches: {recent_batches}"
    )
    return len(old_batches), recent_batches
