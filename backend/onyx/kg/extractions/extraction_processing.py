import json
from collections.abc import Callable

from onyx.db.connector import get_unprocessed_connector_ids
from onyx.db.document import get_unprocessed_kg_documents_for_connector
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_entity_types
from onyx.document_index.vespa.index import KGUChunkpdateRequest
from onyx.document_index.vespa.kg_interactions import update_kg_info_chunks
from onyx.kg.models import ConnectorExtractionStats
from onyx.kg.models import KGChunkExtractionStats
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGChunkId
from onyx.kg.vespa.vespa_interactions import get_document_chunks_for_kg_processing
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import message_to_string
from onyx.prompts.kg_prompts import MASTER_EXTRACTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def _get_entity_types_str(active: bool) -> str:
    """
    Get the entity types from the KGChunkExtraction model.
    """

    with get_session_with_current_tenant() as db_session:
        active_entity_types = get_entity_types(db_session, active)

        entity_types_list = []
        for entity_type in active_entity_types:
            if entity_type.description:
                entity_types_list.append(
                    f"{entity_type.name.upper()}: {entity_type.description}"
                )
            else:
                entity_types_list.append(entity_type.name.upper())

    return "\n".join(entity_types_list)


def kg_extraction_initialization(tenant_id: str, num_chunks: int = 1000) -> None:
    """
    This extraction will create a random sample of chunks to process in order to perform
    clustering and topic modeling.
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")


def kg_extraction(
    tenant_id: str, index_name: str, processing_chunk_batch_size: int = 8
) -> list[ConnectorExtractionStats]:
    """
    This extraction will try to extract from all chunks that have not been kg-processed yet.
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")

    with get_session_with_current_tenant() as db_session:
        connector_ids = get_unprocessed_connector_ids(db_session)

    connector_extraction_stats: list[ConnectorExtractionStats] = []

    processing_chunks: list[KGChunkFormat] = []
    carryover_chunks: list[KGChunkFormat] = []

    for connector_id in connector_ids:
        connector_failed_chunk_extraction_ids: list[KGChunkId] = []
        connector_succeeded_chunk_extraction_ids: list[KGChunkId] = []

        with get_session_with_current_tenant() as db_session:
            unprocessed_documents = get_unprocessed_kg_documents_for_connector(
                db_session,
                connector_id,
            )

            for unprocessed_document in unprocessed_documents:
                formatted_chunk_batches = get_document_chunks_for_kg_processing(
                    unprocessed_document.id,
                    index_name,
                    batch_size=processing_chunk_batch_size,
                )

                for formatted_chunk_batch in formatted_chunk_batches:
                    processing_chunks.extend(formatted_chunk_batch)

                    if len(processing_chunks) >= processing_chunk_batch_size:
                        carryover_chunks.extend(
                            processing_chunks[processing_chunk_batch_size:]
                        )
                        processing_chunks = processing_chunks[
                            :processing_chunk_batch_size
                        ]

                        chunk_processing_batch_results = _kg_chunk_batch_extraction(
                            processing_chunks, index_name, tenant_id
                        )

                        # Consider removing the stats expressions here and rather write to the db(?)
                        connector_failed_chunk_extraction_ids.extend(
                            chunk_processing_batch_results.failed
                        )
                        connector_succeeded_chunk_extraction_ids.extend(
                            chunk_processing_batch_results.succeeded
                        )

                        processing_chunks = carryover_chunks

            # processes remaining chunks
            chunk_processing_batch_results = _kg_chunk_batch_extraction(
                processing_chunks, index_name, tenant_id
            )

            # Consider removing the stats expressions here and rather write to the db(?)
            connector_failed_chunk_extraction_ids.extend(
                chunk_processing_batch_results.failed
            )
            connector_succeeded_chunk_extraction_ids.extend(
                chunk_processing_batch_results.succeeded
            )

        connector_extraction_stats.append(
            ConnectorExtractionStats(
                connector_id=connector_id,
                num_succeeded=len(connector_succeeded_chunk_extraction_ids),
                num_failed=len(connector_failed_chunk_extraction_ids),
            )
        )

    return connector_extraction_stats


def _kg_chunk_batch_extraction(
    chunks: list[KGChunkFormat],
    index_name: str,
    tenant_id: str,
) -> KGChunkExtractionStats:
    _, fast_llm = get_default_llms()

    succeeded_chunks: list[KGChunkId] = []
    failed_chunks: list[KGChunkId] = []

    preformatted_prompt = MASTER_EXTRACTION_PROMPT.format(
        entity_types=_get_entity_types_str(active=True)
    )

    def process_single_chunk(
        chunk: KGChunkFormat, preformatted_prompt: str
    ) -> tuple[bool, KGChunkId]:
        """Process a single chunk and return success status and chunk ID."""

        # For now, we're just processing the content
        # TODO: Implement actual prompt application logic
        formatted_prompt = preformatted_prompt.replace("---content---", chunk.content)

        kg_chunk_id = KGChunkId(document_id=chunk.document_id, chunk_id=chunk.chunk_id)

        try:
            logger.info(
                f"LLM Extraction from chunk {chunk.chunk_id} from doc {chunk.document_id}"
            )
            raw_extraction_result = fast_llm.invoke(formatted_prompt)
            extraction_result = message_to_string(raw_extraction_result)

            try:
                parsed_result = json.loads(extraction_result)
                extracted_entities = parsed_result.get("entities", [])
                extracted_relationships = parsed_result.get("relationships", [])
                extracted_terms = parsed_result.get("terms", [])

                kg_updates = [
                    KGUChunkpdateRequest(
                        doc_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        kg_entities=extracted_entities,
                        kg_relationships=extracted_relationships,
                        kg_terms=extracted_terms,
                    ),
                ]

                update_kg_info_chunks(
                    kg_update_requests=kg_updates,
                    index_name=index_name,
                    tenant_id=tenant_id,
                )

                return True, kg_chunk_id

            except json.JSONDecodeError as e:
                logger.error(
                    f"Invalid JSON format for extraction of chunk {chunk.chunk_id} \
                             from doc {chunk.document_id}: {str(e)}"
                )
                logger.error(f"Raw output: {extraction_result}")
                return False, kg_chunk_id

        except Exception as e:
            logger.error(
                f"Failed to process chunk {chunk.chunk_id} from doc {chunk.document_id}: {str(e)}"
            )
            return False, kg_chunk_id

    use_threads = True
    if use_threads:
        functions_with_args: list[tuple[Callable, tuple]] = [
            (process_single_chunk, (chunk, preformatted_prompt)) for chunk in chunks
        ]

        logger.debug("Running KG extraction on chunks in parallel")
        results = run_functions_tuples_in_parallel(
            functions_with_args, allow_failures=True
        )

        # Sort results into succeeded and failed
        for success, chunk_id in results:
            if success:
                succeeded_chunks.append(chunk_id)
            else:
                failed_chunks.append(chunk_id)

        return KGChunkExtractionStats(
            connector_id=chunks[0].connector_id if chunks else None,  # TODO: Update!
            succeeded=succeeded_chunks,
            failed=failed_chunks,
        )

    else:
        for chunk in chunks:
            success, chunk_id = process_single_chunk(chunk, preformatted_prompt)
            if success:
                succeeded_chunks.append(chunk_id)
            else:
                failed_chunks.append(chunk_id)

        return KGChunkExtractionStats(
            connector_id=chunks[0].connector_id if chunks else None,  # TODO: Update!
            succeeded=succeeded_chunks,
            failed=failed_chunks,
        )


def _kg_connector_extraction(
    connector_id: str,
    tenant_id: str,
) -> None:
    logger.info(
        f"Starting kg extraction for connector {connector_id} for tenant {tenant_id}"
    )

    # - grab kg type data from postgres

    # - construct prompt

    # find all documents for the connector that have not been kg-processed

    # - loop for :

    # - grab a number of chunks from vespa

    # - convert them into the KGChunk format

    # - run the extractions in parallel

    # - save the results

    # - mark chunks as processed

    # - update the connector status


#
