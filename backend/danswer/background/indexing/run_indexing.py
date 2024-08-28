import time
import traceback
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy.orm import Session

from danswer.background.indexing.checkpointing import get_time_windows_for_index_attempt
from danswer.background.indexing.tracer import DanswerTracer
from danswer.configs.app_configs import INDEXING_SIZE_WARNING_THRESHOLD
from danswer.configs.app_configs import INDEXING_TRACER_INTERVAL
from danswer.configs.app_configs import POLL_CONNECTOR_OFFSET
from danswer.connectors.connector_runner import ConnectorRunner
from danswer.connectors.factory import instantiate_connector
from danswer.connectors.models import IndexAttemptMetadata
from danswer.db.connector_credential_pair import get_last_successful_attempt_time
from danswer.db.connector_credential_pair import update_connector_credential_pair
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.index_attempt import get_index_attempt
from danswer.db.index_attempt import mark_attempt_failed
from danswer.db.index_attempt import mark_attempt_in_progress
from danswer.db.index_attempt import mark_attempt_partially_succeeded
from danswer.db.index_attempt import mark_attempt_succeeded
from danswer.db.index_attempt import update_docs_indexed
from danswer.db.models import IndexAttempt
from danswer.db.models import IndexingStatus
from danswer.db.models import IndexModelStatus
from danswer.document_index.factory import get_default_document_index
from danswer.indexing.embedder import DefaultIndexingEmbedder
from danswer.indexing.indexing_pipeline import build_indexing_pipeline
from danswer.utils.logger import IndexAttemptSingleton
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import global_version

logger = setup_logger()

INDEXING_TRACER_NUM_PRINT_ENTRIES = 5


def _get_connector_runner(
    db_session: Session,
    attempt: IndexAttempt,
    start_time: datetime,
    end_time: datetime,
) -> ConnectorRunner:
    """
    NOTE: `start_time` and `end_time` are only used for poll connectors

    Returns an interator of document batches and whether the returned documents
    are the complete list of existing documents of the connector. If the task
    of type LOAD_STATE, the list will be considered complete and otherwise incomplete.
    """
    task = attempt.connector_credential_pair.connector.input_type

    try:
        runnable_connector = instantiate_connector(
            attempt.connector_credential_pair.connector.source,
            task,
            attempt.connector_credential_pair.connector.connector_specific_config,
            attempt.connector_credential_pair.credential,
            db_session,
        )
    except Exception as e:
        logger.exception(f"Unable to instantiate connector due to {e}")
        # since we failed to even instantiate the connector, we pause the CCPair since
        # it will never succeed
        update_connector_credential_pair(
            db_session=db_session,
            connector_id=attempt.connector_credential_pair.connector.id,
            credential_id=attempt.connector_credential_pair.credential.id,
            status=ConnectorCredentialPairStatus.PAUSED,
        )
        raise e

    return ConnectorRunner(
        connector=runnable_connector, time_range=(start_time, end_time)
    )


def _run_indexing(
    db_session: Session,
    index_attempt: IndexAttempt,
) -> None:
    """
    1. Get documents which are either new or updated from specified application
    2. Embed and index these documents into the chosen datastore (vespa)
    3. Updates Postgres to record the indexed documents + the outcome of this run
    """
    start_time = time.time()

    db_embedding_model = index_attempt.embedding_model
    index_name = db_embedding_model.index_name

    # Only update cc-pair status for primary index jobs
    # Secondary index syncs at the end when swapping
    is_primary = index_attempt.embedding_model.status == IndexModelStatus.PRESENT

    # Indexing is only done into one index at a time
    document_index = get_default_document_index(
        primary_index_name=index_name, secondary_index_name=None
    )

    embedding_model = DefaultIndexingEmbedder.from_db_embedding_model(
        db_embedding_model
    )

    indexing_pipeline = build_indexing_pipeline(
        attempt_id=index_attempt.id,
        embedder=embedding_model,
        document_index=document_index,
        ignore_time_skip=index_attempt.from_beginning
        or (db_embedding_model.status == IndexModelStatus.FUTURE),
        db_session=db_session,
    )

    db_cc_pair = index_attempt.connector_credential_pair
    db_connector = index_attempt.connector_credential_pair.connector
    db_credential = index_attempt.connector_credential_pair.credential

    last_successful_index_time = (
        db_connector.indexing_start.timestamp()
        if index_attempt.from_beginning and db_connector.indexing_start is not None
        else (
            0.0
            if index_attempt.from_beginning
            else get_last_successful_attempt_time(
                connector_id=db_connector.id,
                credential_id=db_credential.id,
                embedding_model=index_attempt.embedding_model,
                db_session=db_session,
            )
        )
    )

    if INDEXING_TRACER_INTERVAL > 0:
        logger.debug(f"Memory tracer starting: interval={INDEXING_TRACER_INTERVAL}")
        tracer = DanswerTracer()
        tracer.start()
        tracer.snap()

    index_attempt_md = IndexAttemptMetadata(
        connector_id=db_connector.id,
        credential_id=db_credential.id,
    )

    batch_num = 0
    net_doc_change = 0
    document_count = 0
    chunk_count = 0
    run_end_dt = None
    for ind, (window_start, window_end) in enumerate(
        get_time_windows_for_index_attempt(
            last_successful_run=datetime.fromtimestamp(
                last_successful_index_time, tz=timezone.utc
            ),
            source_type=db_connector.source,
        )
    ):
        try:
            window_start = max(
                window_start - timedelta(minutes=POLL_CONNECTOR_OFFSET),
                datetime(1970, 1, 1, tzinfo=timezone.utc),
            )

            connector_runner = _get_connector_runner(
                db_session=db_session,
                attempt=index_attempt,
                start_time=window_start,
                end_time=window_end,
            )

            all_connector_doc_ids: set[str] = set()

            tracer_counter = 0
            if INDEXING_TRACER_INTERVAL > 0:
                tracer.snap()
            for doc_batch in connector_runner.run():
                # Check if connector is disabled mid run and stop if so unless it's the secondary
                # index being built. We want to populate it even for paused connectors
                # Often paused connectors are sources that aren't updated frequently but the
                # contents still need to be initially pulled.
                db_session.refresh(db_connector)
                if (
                    (
                        db_cc_pair.status == ConnectorCredentialPairStatus.PAUSED
                        and db_embedding_model.status != IndexModelStatus.FUTURE
                    )
                    # if it's deleting, we don't care if this is a secondary index
                    or db_cc_pair.status == ConnectorCredentialPairStatus.DELETING
                ):
                    # let the `except` block handle this
                    raise RuntimeError("Connector was disabled mid run")

                db_session.refresh(index_attempt)
                if index_attempt.status != IndexingStatus.IN_PROGRESS:
                    # Likely due to user manually disabling it or model swap
                    raise RuntimeError("Index Attempt was canceled")

                batch_description = []
                for doc in doc_batch:
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
                new_docs, total_batch_chunks = indexing_pipeline(
                    document_batch=doc_batch,
                    index_attempt_metadata=index_attempt_md,
                )

                batch_num += 1
                net_doc_change += new_docs
                chunk_count += total_batch_chunks
                document_count += len(doc_batch)
                all_connector_doc_ids.update(doc.id for doc in doc_batch)

                # commit transaction so that the `update` below begins
                # with a brand new transaction. Postgres uses the start
                # of the transactions when computing `NOW()`, so if we have
                # a long running transaction, the `time_updated` field will
                # be inaccurate
                db_session.commit()

                # This new value is updated every batch, so UI can refresh per batch update
                update_docs_indexed(
                    db_session=db_session,
                    index_attempt=index_attempt,
                    total_docs_indexed=document_count,
                    new_docs_indexed=net_doc_change,
                    docs_removed_from_index=0,
                )

                tracer_counter += 1
                if (
                    INDEXING_TRACER_INTERVAL > 0
                    and tracer_counter % INDEXING_TRACER_INTERVAL == 0
                ):
                    logger.debug(
                        f"Running trace comparison for batch {tracer_counter}. interval={INDEXING_TRACER_INTERVAL}"
                    )
                    tracer.snap()
                    tracer.log_previous_diff(INDEXING_TRACER_NUM_PRINT_ENTRIES)

            run_end_dt = window_end
            if is_primary:
                update_connector_credential_pair(
                    db_session=db_session,
                    connector_id=db_connector.id,
                    credential_id=db_credential.id,
                    net_docs=net_doc_change,
                    run_dt=run_end_dt,
                )
        except Exception as e:
            logger.exception(
                f"Connector run ran into exception after elapsed time: {time.time() - start_time} seconds"
            )
            # Only mark the attempt as a complete failure if this is the first indexing window.
            # Otherwise, some progress was made - the next run will not start from the beginning.
            # In this case, it is not accurate to mark it as a failure. When the next run begins,
            # if that fails immediately, it will be marked as a failure.
            #
            # NOTE: if the connector is manually disabled, we should mark it as a failure regardless
            # to give better clarity in the UI, as the next run will never happen.
            if (
                ind == 0
                or not db_cc_pair.status.is_active()
                or index_attempt.status != IndexingStatus.IN_PROGRESS
            ):
                mark_attempt_failed(
                    index_attempt,
                    db_session,
                    failure_reason=str(e),
                    full_exception_trace=traceback.format_exc(),
                )
                if is_primary:
                    update_connector_credential_pair(
                        db_session=db_session,
                        connector_id=db_connector.id,
                        credential_id=db_credential.id,
                        net_docs=net_doc_change,
                    )

                if INDEXING_TRACER_INTERVAL > 0:
                    tracer.stop()
                raise e

            # break => similar to success case. As mentioned above, if the next run fails for the same
            # reason it will then be marked as a failure
            break

    if INDEXING_TRACER_INTERVAL > 0:
        logger.debug(
            f"Running trace comparison between start and end of indexing. {tracer_counter} batches processed."
        )
        tracer.snap()
        tracer.log_first_diff(INDEXING_TRACER_NUM_PRINT_ENTRIES)
        tracer.stop()
        logger.debug("Memory tracer stopped.")

    if (
        index_attempt_md.num_exceptions > 0
        and index_attempt_md.num_exceptions >= batch_num
    ):
        mark_attempt_failed(
            index_attempt,
            db_session,
            failure_reason="All batches exceptioned.",
        )
        if is_primary:
            update_connector_credential_pair(
                db_session=db_session,
                connector_id=index_attempt.connector_credential_pair.connector.id,
                credential_id=index_attempt.connector_credential_pair.credential.id,
            )
        raise Exception(
            f"Connector failed - All batches exceptioned: batches={batch_num}"
        )

    elapsed_time = time.time() - start_time

    if index_attempt_md.num_exceptions == 0:
        mark_attempt_succeeded(index_attempt, db_session)
        logger.info(
            f"Connector succeeded: "
            f"docs={document_count} chunks={chunk_count} elapsed={elapsed_time:.2f}s"
        )
    else:
        mark_attempt_partially_succeeded(index_attempt, db_session)
        logger.info(
            f"Connector completed with some errors: "
            f"exceptions={index_attempt_md.num_exceptions} "
            f"batches={batch_num} "
            f"docs={document_count} "
            f"chunks={chunk_count} "
            f"elapsed={elapsed_time:.2f}s"
        )

    if is_primary:
        update_connector_credential_pair(
            db_session=db_session,
            connector_id=db_connector.id,
            credential_id=db_credential.id,
            run_dt=run_end_dt,
        )


def _prepare_index_attempt(db_session: Session, index_attempt_id: int) -> IndexAttempt:
    # make sure that the index attempt can't change in between checking the
    # status and marking it as in_progress. This setting will be discarded
    # after the next commit:
    # https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#setting-isolation-for-individual-transactions
    db_session.connection(execution_options={"isolation_level": "SERIALIZABLE"})  # type: ignore

    attempt = get_index_attempt(
        db_session=db_session,
        index_attempt_id=index_attempt_id,
    )

    if attempt is None:
        raise RuntimeError(f"Unable to find IndexAttempt for ID '{index_attempt_id}'")

    if attempt.status != IndexingStatus.NOT_STARTED:
        raise RuntimeError(
            f"Indexing attempt with ID '{index_attempt_id}' is not in NOT_STARTED status. "
            f"Current status is '{attempt.status}'."
        )

    # only commit once, to make sure this all happens in a single transaction
    mark_attempt_in_progress(attempt, db_session)

    return attempt


def run_indexing_entrypoint(index_attempt_id: int, is_ee: bool = False) -> None:
    """Entrypoint for indexing run when using dask distributed.
    Wraps the actual logic in a `try` block so that we can catch any exceptions
    and mark the attempt as failed."""
    try:
        if is_ee:
            global_version.set_ee()

        # set the indexing attempt ID so that all log messages from this process
        # will have it added as a prefix
        IndexAttemptSingleton.set_index_attempt_id(index_attempt_id)

        with Session(get_sqlalchemy_engine()) as db_session:
            # make sure that it is valid to run this indexing attempt + mark it
            # as in progress
            attempt = _prepare_index_attempt(db_session, index_attempt_id)

            logger.info(
                f"Indexing starting: "
                f"connector='{attempt.connector_credential_pair.connector.name}' "
                f"config='{attempt.connector_credential_pair.connector.connector_specific_config}' "
                f"credentials='{attempt.connector_credential_pair.connector_id}'"
            )

            _run_indexing(db_session, attempt)

            logger.info(
                f"Indexing finished: "
                f"connector='{attempt.connector_credential_pair.connector.name}' "
                f"config='{attempt.connector_credential_pair.connector.connector_specific_config}' "
                f"credentials='{attempt.connector_credential_pair.connector_id}'"
            )
    except Exception as e:
        logger.exception(f"Indexing job with ID '{index_attempt_id}' failed due to {e}")
