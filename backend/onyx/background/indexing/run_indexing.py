import time
import traceback
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.background.indexing.checkpointing_utils import get_latest_valid_checkpoint
from onyx.background.indexing.checkpointing_utils import save_checkpoint
from onyx.background.indexing.memory_tracer import MemoryTracer
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import INDEXING_SIZE_WARNING_THRESHOLD
from onyx.configs.app_configs import INDEXING_TRACER_INTERVAL
from onyx.configs.app_configs import LEAVE_CONNECTOR_ACTIVE_ON_INITIALIZATION_FAILURE
from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MilestoneRecordType
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_last_successful_attempt_time
from onyx.db.connector_credential_pair import update_connector_credential_pair
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
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
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import IndexingStatus
from onyx.db.models import IndexModelStatus
from onyx.document_index.factory import get_default_document_index
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.indexing.indexing_pipeline import build_indexing_pipeline
from onyx.utils.logger import setup_logger
from onyx.utils.logger import TaskAttemptSingleton
from onyx.utils.telemetry import create_milestone_and_report
from onyx.utils.variable_functionality import global_version

logger = setup_logger()

INDEXING_TRACER_NUM_PRINT_ENTRIES = 5


def _get_connector_runner(
    db_session: Session,
    attempt: IndexAttempt,
    batch_size: int,
    start_time: datetime,
    end_time: datetime,
    tenant_id: str | None,
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
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.exception(f"Unable to instantiate connector due to {e}")

        # since we failed to even instantiate the connector, we pause the CCPair since
        # it will never succeed. Sometimes there are cases where the connector will
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
        time_range=(start_time, end_time),
    )


def strip_null_characters(doc_batch: list[Document]) -> list[Document]:
    cleaned_batch = []
    for doc in doc_batch:
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
            if section.link and "\x00" in section.link:
                logger.warning(
                    f"NUL characters found in document link for document: {cleaned_doc.id}"
                )
                section.link = section.link.replace("\x00", "")

            # since text can be longer, just replace to avoid double scan
            section.text = section.text.replace("\x00", "")

        cleaned_batch.append(cleaned_doc)

    return cleaned_batch


class ConnectorStopSignal(Exception):
    """A custom exception used to signal a stop in processing."""


class RunIndexingContext(BaseModel):
    index_name: str
    cc_pair_id: int
    connector_id: int
    credential_id: int
    source: DocumentSource
    earliest_index_time: float
    from_beginning: bool
    is_primary: bool
    search_settings_status: IndexModelStatus


def _check_connector_and_attempt_status(
    db_session_temp: Session, ctx: RunIndexingContext, index_attempt_id: int
) -> None:
    """
    Checks the status of the connector credential pair and index attempt.
    Raises a RuntimeError if any conditions are not met.
    """
    cc_pair_loop = get_connector_credential_pair_from_id(
        db_session_temp,
        ctx.cc_pair_id,
    )
    if not cc_pair_loop:
        raise RuntimeError(f"CC pair {ctx.cc_pair_id} not found in DB.")

    if (
        cc_pair_loop.status == ConnectorCredentialPairStatus.PAUSED
        and ctx.search_settings_status != IndexModelStatus.FUTURE
    ) or cc_pair_loop.status == ConnectorCredentialPairStatus.DELETING:
        raise RuntimeError("Connector was disabled mid run")

    index_attempt_loop = get_index_attempt(db_session_temp, index_attempt_id)
    if not index_attempt_loop:
        raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")

    if index_attempt_loop.status != IndexingStatus.IN_PROGRESS:
        raise RuntimeError(
            f"Index Attempt was canceled, status is {index_attempt_loop.status}"
        )


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


def _run_indexing(
    db_session: Session,
    index_attempt_id: int,
    tenant_id: str | None,
    callback: IndexingHeartbeatInterface | None = None,
) -> None:
    """
    1. Get documents which are either new or updated from specified application
    2. Embed and index these documents into the chosen datastore (vespa)
    3. Updates Postgres to record the indexed documents + the outcome of this run
    """
    start_time = time.monotonic()  # jsut used for logging

    with get_session_with_current_tenant() as db_session_temp:
        index_attempt_start = get_index_attempt(db_session_temp, index_attempt_id)
        if not index_attempt_start:
            raise ValueError(
                f"Index attempt {index_attempt_id} does not exist in DB. This should not be possible."
            )

        if index_attempt_start.search_settings is None:
            raise ValueError(
                "Search settings must be set for indexing. This should not be possible."
            )

        # search_settings = index_attempt_start.search_settings
        db_connector = index_attempt_start.connector_credential_pair.connector
        db_credential = index_attempt_start.connector_credential_pair.credential
        ctx = RunIndexingContext(
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
            from_beginning=index_attempt_start.from_beginning,
            # Only update cc-pair status for primary index jobs
            # Secondary index syncs at the end when swapping
            is_primary=(
                index_attempt_start.search_settings.status == IndexModelStatus.PRESENT
            ),
            search_settings_status=index_attempt_start.search_settings.status,
        )

        last_successful_index_time = (
            ctx.earliest_index_time
            if ctx.from_beginning
            else get_last_successful_attempt_time(
                connector_id=ctx.connector_id,
                credential_id=ctx.credential_id,
                earliest_index=ctx.earliest_index_time,
                search_settings=index_attempt_start.search_settings,
                db_session=db_session_temp,
            )
        )
        if last_successful_index_time > POLL_CONNECTOR_OFFSET:
            window_start = datetime.fromtimestamp(
                last_successful_index_time, tz=timezone.utc
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

    document_index = get_default_document_index(
        index_attempt_start.search_settings,
        None,
        httpx_client=HttpxPool.get("vespa"),
    )

    indexing_pipeline = build_indexing_pipeline(
        embedder=embedding_model,
        document_index=document_index,
        ignore_time_skip=(
            ctx.from_beginning
            or (ctx.search_settings_status == IndexModelStatus.FUTURE)
        ),
        db_session=db_session,
        tenant_id=tenant_id,
        callback=callback,
    )

    # Initialize memory tracer. NOTE: won't actually do anything if
    # `INDEXING_TRACER_INTERVAL` is 0.
    memory_tracer = MemoryTracer(interval=INDEXING_TRACER_INTERVAL)
    memory_tracer.start()

    index_attempt_md = IndexAttemptMetadata(
        connector_id=ctx.connector_id,
        credential_id=ctx.credential_id,
    )

    total_failures = 0
    batch_num = 0
    net_doc_change = 0
    document_count = 0
    chunk_count = 0
    try:
        with get_session_with_current_tenant() as db_session_temp:
            index_attempt = get_index_attempt(db_session_temp, index_attempt_id)
            if not index_attempt:
                raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")

            connector_runner = _get_connector_runner(
                db_session=db_session_temp,
                attempt=index_attempt,
                batch_size=INDEX_BATCH_SIZE,
                start_time=window_start,
                end_time=window_end,
                tenant_id=tenant_id,
            )

            # don't use a checkpoint if we're explicitly indexing from
            # the beginning in order to avoid weird interactions between
            # checkpointing / failure handling.
            if index_attempt.from_beginning:
                checkpoint = ConnectorCheckpoint.build_dummy_checkpoint()
            else:
                checkpoint = get_latest_valid_checkpoint(
                    db_session=db_session_temp,
                    cc_pair_id=ctx.cc_pair_id,
                    search_settings_id=index_attempt.search_settings_id,
                    window_start=window_start,
                    window_end=window_end,
                )

            unresolved_errors = get_index_attempt_errors_for_cc_pair(
                cc_pair_id=ctx.cc_pair_id,
                unresolved_only=True,
                db_session=db_session_temp,
            )
            doc_id_to_unresolved_errors: dict[
                str, list[IndexAttemptError]
            ] = defaultdict(list)
            for error in unresolved_errors:
                if error.document_id:
                    doc_id_to_unresolved_errors[error.document_id].append(error)

            entity_based_unresolved_errors = [
                error for error in unresolved_errors if error.entity_id
            ]

        while checkpoint.has_more:
            logger.info(
                f"Running '{ctx.source}' connector with checkpoint: {checkpoint}"
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

                # TODO: should we move this into the above callback instead?
                with get_session_with_current_tenant() as db_session_temp:
                    # will exception if the connector/index attempt is marked as paused/failed
                    _check_connector_and_attempt_status(
                        db_session_temp, ctx, index_attempt_id
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

                doc_batch_cleaned = strip_null_characters(document_batch)
                for doc in doc_batch_cleaned:
                    batch_description.append(doc.to_short_descriptor())

                    doc_size = 0
                    for section in doc.sections:
                        doc_size += len(section.text)

                    if doc_size > INDEXING_SIZE_WARNING_THRESHOLD:
                        logger.warning(
                            f"Document size: doc='{doc.to_short_descriptor()}' "
                            f"size={doc_size} "
                            f"threshold={INDEXING_SIZE_WARNING_THRESHOLD}"
                        )

                logger.debug(f"Indexing batch of documents: {batch_description}")

                index_attempt_md.batch_num = batch_num + 1  # use 1-index for this

                # real work happens here!
                index_pipeline_result = indexing_pipeline(
                    document_batch=doc_batch_cleaned,
                    index_attempt_metadata=index_attempt_md,
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

    except Exception as e:
        logger.exception(
            "Connector run exceptioned after elapsed time: "
            f"{time.monotonic() - start_time} seconds"
        )

        if isinstance(e, ConnectorStopSignal):
            with get_session_with_current_tenant() as db_session_temp:
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


def run_indexing_entrypoint(
    index_attempt_id: int,
    tenant_id: str | None,
    connector_credential_pair_id: int,
    is_ee: bool = False,
    callback: IndexingHeartbeatInterface | None = None,
) -> None:
    """Don't swallow exceptions here ... propagate them up."""

    if is_ee:
        global_version.set_ee()

    # set the indexing attempt ID so that all log messages from this process
    # will have it added as a prefix
    TaskAttemptSingleton.set_cc_and_index_id(
        index_attempt_id, connector_credential_pair_id
    )
    with get_session_with_current_tenant() as db_session:
        # TODO: remove long running session entirely
        attempt = transition_attempt_to_in_progress(index_attempt_id, db_session)

        tenant_str = ""
        if tenant_id is not None:
            tenant_str = f" for tenant {tenant_id}"

        connector_name = attempt.connector_credential_pair.connector.name
        connector_config = (
            attempt.connector_credential_pair.connector.connector_specific_config
        )
        credential_id = attempt.connector_credential_pair.credential_id

    logger.info(
        f"Indexing starting{tenant_str}: "
        f"connector='{connector_name}' "
        f"config='{connector_config}' "
        f"credentials='{credential_id}'"
    )

    with get_session_with_current_tenant() as db_session:
        _run_indexing(db_session, index_attempt_id, tenant_id, callback)

    logger.info(
        f"Indexing finished{tenant_str}: "
        f"connector='{connector_name}' "
        f"config='{connector_config}' "
        f"credentials='{credential_id}'"
    )
