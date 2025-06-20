import time
import traceback
from http import HTTPStatus

from celery import shared_task
from celery import Task
from pydantic import BaseModel

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.index_attempt import update_docs_indexed
from onyx.document_index.factory import get_default_document_index
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import build_indexing_pipeline
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.redis.redis_connector import RedisConnector
from onyx.storage.document_batch_storage import get_document_batch_storage
from onyx.utils.logger import setup_logger
from onyx.utils.middleware import make_randomized_onyx_request_id
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class DocumentProcessingBatch(BaseModel):
    """Data structure for a document processing batch."""

    batch_id: str
    index_attempt_id: int
    cc_pair_id: int
    tenant_id: str
    batch_num: int


@shared_task(
    name=OnyxCeleryTask.DOCUMENT_INDEXING_PIPELINE_TASK,
    bind=True,
)
def document_indexing_pipeline_task(
    self: Task,
    batch_id: str,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
) -> None:
    """Process a batch of documents through the indexing pipeline.

    This task retrieves documents from storage and processes them through
    the indexing pipeline (embedding + vector store indexing).
    """

    start_time = time.monotonic()

    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Processing document batch: "
        f"batch_id={batch_id} "
        f"attempt={index_attempt_id} "
        f"batch_num={batch_num} "
    )

    # Get the document batch storage
    storage = get_document_batch_storage(tenant_id, index_attempt_id)

    try:
        # Retrieve documents from storage
        documents = storage.get_batch(batch_id)
        if not documents:
            task_logger.error(f"No documents found for batch {batch_id}")
            return

        with get_session_with_current_tenant() as db_session:
            # matches parts of _run_indexing
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

            # TODO: pass in callback
            # Set up indexing pipeline components
            embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
                search_settings=index_attempt.search_settings,
                callback=None,
            )

            information_content_classification_model = (
                InformationContentClassificationModel()
            )

            document_index = get_default_document_index(
                index_attempt.search_settings,
                None,
                httpx_client=HttpxPool.get("vespa"),
            )

            indexing_pipeline = build_indexing_pipeline(
                embedder=embedding_model,
                information_content_classification_model=information_content_classification_model,
                document_index=document_index,
                ignore_time_skip=True,  # Documents are already filtered during extraction
                db_session=db_session,
                tenant_id=tenant_id,
                callback=None,
            )

            # Set up metadata for this batch
            index_attempt_metadata = IndexAttemptMetadata(
                attempt_id=index_attempt_id,
                connector_id=index_attempt.connector_credential_pair.connector.id,
                credential_id=index_attempt.connector_credential_pair.credential.id,
                request_id=make_randomized_onyx_request_id("DIP"),
                structured_id=f"{tenant_id}:{cc_pair_id}:{index_attempt_id}:{batch_num}",
                batch_num=batch_num,
            )

            # Process documents through indexing pipeline
            task_logger.info(
                f"Processing {len(documents)} documents through indexing pipeline"
            )

            index_pipeline_result = indexing_pipeline(
                document_batch=documents,
                index_attempt_metadata=index_attempt_metadata,
            )

            # # Update extraction state with batch results
            storage.get_extraction_state()
            # if current_state:
            #     current_state["total_docs_processed"] = (
            #         current_state.get("total_docs_processed", 0)
            #         + index_pipeline_result.total_docs
            #     )
            #     current_state["total_chunks_created"] = (
            #         current_state.get("total_chunks_created", 0)
            #         + index_pipeline_result.total_chunks
            #     )
            #     current_state["net_doc_change"] = (
            #         current_state.get("net_doc_change", 0)
            #         + index_pipeline_result.new_docs
            #     )
            #     current_state["batches_processed"] = (
            #         current_state.get("batches_processed", 0) + 1
            #     )

            #     if index_pipeline_result.failures:
            #         current_state["total_failures"] = current_state.get(
            #             "total_failures", 0
            #         ) + len(index_pipeline_result.failures)

            #     storage.store_extraction_state(current_state)

            # TODO: use lock to avoid race conditions between workers
            # when reading/writing db
            # Record failures in the database
            if index_pipeline_result.failures:
                for failure in index_pipeline_result.failures:
                    create_index_attempt_error(
                        index_attempt_id,
                        cc_pair_id,
                        failure,
                        db_session,
                    )

            # # Update docs indexed count
            # total_docs_indexed = (
            #     current_state.get(
            #         "total_docs_processed", index_pipeline_result.total_docs
            #     )
            #     if current_state
            #     else index_pipeline_result.total_docs
            # )
            # net_doc_change = (
            #     current_state.get("net_doc_change", index_pipeline_result.new_docs)
            #     if current_state
            #     else index_pipeline_result.new_docs
            # )

            update_docs_indexed(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_docs_indexed=index_pipeline_result.total_docs,
                new_docs_indexed=index_pipeline_result.new_docs,
                docs_removed_from_index=0,
            )

        # Clean up this batch after successful processing
        storage.delete_batch(batch_id)

        elapsed_time = time.monotonic() - start_time
        task_logger.info(
            f"Completed document batch processing: "
            f"batch_id={batch_id} "
            f"docs={len(documents)} "
            f"chunks={index_pipeline_result.total_chunks} "
            f"failures={len(index_pipeline_result.failures)} "
            f"elapsed={elapsed_time:.2f}s"
        )
        # TODO: last batch logic
        if False:
            # TODO: out of order batch completion logic for setting completion and checkpointing
            redis_connector = RedisConnector(tenant_id, cc_pair_id)
            redis_connector_index = redis_connector.new_index(
                index_attempt.search_settings.id
            )
            # mark as done
            redis_connector_index.set_generator_complete(HTTPStatus.OK.value)

    except Exception as e:
        task_logger.exception(
            f"Document batch processing failed: "
            f"batch_id={batch_id} "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
        )

        # Record the failure
        # try:
        #     with get_session_with_current_tenant() as db_session:
        #         create_index_attempt_error(
        #             index_attempt_id,
        #             cc_pair_id,
        #             str(e),
        #             db_session,
        #         )
        # except Exception:
        #     task_logger.exception("Failed to record processing error in database")

        raise


@shared_task(
    name=OnyxCeleryTask.MONITOR_DOCPROCESSING_COMPLETION,
    bind=True,
)
def monitor_docprocessing_completion(
    self: Task,
    index_attempt_id: int,
    tenant_id: str,
) -> None:
    """Monitor the completion of document processing and finalize the index attempt.

    This task checks if all document batches have been processed and marks
    the index attempt as succeeded or failed accordingly.
    """
    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Monitoring document processing completion: " f"attempt={index_attempt_id}"
    )

    storage = get_document_batch_storage(tenant_id, index_attempt_id)

    try:
        # Get current state
        state = storage.get_extraction_state()
        if not state:
            task_logger.warning(
                f"No extraction state found for attempt {index_attempt_id}"
            )
            return

        # Check if extraction is complete and all batches are processed
        extraction_completed = state.doc_extraction_completed
        batches_total = state.batches_total
        batches_processed = state.is_batch_processed.count(True)

        task_logger.info(
            f"Processing status: "
            f"extraction_completed={extraction_completed} "
            f"batches_processed={batches_processed}/{batches_total}"
        )

        if extraction_completed and batches_processed >= batches_total:
            # All processing is complete
            total_failures = state.total_failures

            with get_session_with_current_tenant() as db_session:
                if total_failures == 0:
                    mark_attempt_succeeded(index_attempt_id, db_session)
                    task_logger.info(
                        f"Index attempt {index_attempt_id} completed successfully"
                    )
                else:
                    mark_attempt_partially_succeeded(index_attempt_id, db_session)
                    task_logger.info(
                        f"Index attempt {index_attempt_id} completed with {total_failures} failures"
                    )

            # Clean up all remaining storage
            storage.cleanup_all_batches()

        else:
            # Processing not yet complete, schedule another check
            if not extraction_completed:
                # If extraction isn't complete, check again sooner
                countdown = 30
            else:
                # If extraction is complete but processing isn't, check more frequently
                countdown = 10

            task_logger.info(
                f"Processing not yet complete, rescheduling check in {countdown}s"
            )

            self.app.send_task(
                OnyxCeleryTask.MONITOR_DOCPROCESSING_COMPLETION,
                kwargs={
                    "index_attempt_id": index_attempt_id,
                    "tenant_id": tenant_id,
                },
                countdown=countdown,
            )

    except Exception as e:
        task_logger.exception(
            f"Failed to monitor document processing completion: "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
        )

        # Mark the attempt as failed if monitoring fails
        try:
            with get_session_with_current_tenant() as db_session:
                mark_attempt_failed(
                    index_attempt_id,
                    db_session,
                    failure_reason=f"Processing monitoring failed: {str(e)}",
                    full_exception_trace=traceback.format_exc(),
                )
        except Exception:
            task_logger.exception("Failed to mark attempt as failed")

        # Try to clean up storage
        try:
            storage.cleanup_all_batches()
        except Exception:
            task_logger.exception("Failed to cleanup storage after monitoring failure")
