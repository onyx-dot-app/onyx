import json
from collections import defaultdict
from collections.abc import Callable

from onyx.db.connector import get_unprocessed_connector_ids
from onyx.db.document import get_unprocessed_kg_documents_for_connector
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import get_entity_types
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.document_index.vespa.index import KGUChunkpdateRequest
from onyx.document_index.vespa.kg_interactions import update_kg_chunks_vespa_info
from onyx.kg.models import ConnectorExtractionStats
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGBatchExtractionStats
from onyx.kg.models import KGChunkExtraction
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGChunkId
from onyx.kg.utils.chunk_preprocessing import prepare_llm_content
from onyx.kg.utils.formatting_utils import aggregate_kg_extractions
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
                    f"{entity_type.id_name}: {entity_type.description}"
                )
            else:
                entity_types_list.append(entity_type.id_name)

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
    connector_aggregated_kg_extractions_list: list[KGAggregatedExtractions] = []

    for connector_id in connector_ids:
        connector_failed_chunk_extractions: list[KGChunkId] = []
        connector_succeeded_chunk_extractions: list[KGChunkId] = []
        connector_aggregated_kg_extractions: KGAggregatedExtractions = (
            KGAggregatedExtractions(
                entities=defaultdict(int),
                relationships=defaultdict(int),
                terms=defaultdict(int),
            )
        )

        with get_session_with_current_tenant() as db_session:
            unprocessed_documents = get_unprocessed_kg_documents_for_connector(
                db_session,
                connector_id,
            )

            # TODO: restricted for testing only
            unprocessed_documents_list = list(unprocessed_documents)

        unprocessed_documents_list = [
            unprocessed_documents_list[0],
            unprocessed_documents_list[6],
        ]
        for unprocessed_document in unprocessed_documents_list:
            formatted_chunk_batches = get_document_chunks_for_kg_processing(
                unprocessed_document.id,
                index_name,
                batch_size=processing_chunk_batch_size,
            )

            formatted_chunk_batches_list = list(formatted_chunk_batches)

            for formatted_chunk_batch in formatted_chunk_batches_list:
                processing_chunks.extend(formatted_chunk_batch)

                if len(processing_chunks) >= processing_chunk_batch_size:
                    carryover_chunks.extend(
                        processing_chunks[processing_chunk_batch_size:]
                    )
                    processing_chunks = processing_chunks[:processing_chunk_batch_size]

                    chunk_processing_batch_results = _kg_chunk_batch_extraction(
                        processing_chunks, index_name, tenant_id
                    )

                    # Consider removing the stats expressions here and rather write to the db(?)
                    connector_failed_chunk_extractions.extend(
                        chunk_processing_batch_results.failed
                    )
                    connector_succeeded_chunk_extractions.extend(
                        chunk_processing_batch_results.succeeded
                    )

                    aggregated_batch_extractions = (
                        chunk_processing_batch_results.aggregated_kg_extractions
                    )
                    connector_aggregated_kg_extractions.entities.update(
                        aggregated_batch_extractions.entities
                    )
                    connector_aggregated_kg_extractions.relationships.update(
                        aggregated_batch_extractions.relationships
                    )
                    connector_aggregated_kg_extractions.terms.update(
                        aggregated_batch_extractions.terms
                    )

                    processing_chunks = carryover_chunks.copy()
                    carryover_chunks = []

                    connector_extraction_stats.append(
                        ConnectorExtractionStats(
                            connector_id=connector_id,
                            num_failed=len(connector_failed_chunk_extractions),
                            num_succeeded=len(connector_succeeded_chunk_extractions),
                            num_processed=len(processing_chunks),
                        )
                    )

        # processes remaining chunks
        chunk_processing_batch_results = _kg_chunk_batch_extraction(
            processing_chunks, index_name, tenant_id
        )

        # Consider removing the stats expressions here and rather write to the db(?)
        connector_failed_chunk_extractions.extend(chunk_processing_batch_results.failed)
        connector_succeeded_chunk_extractions.extend(
            chunk_processing_batch_results.succeeded
        )

        aggregated_batch_extractions = (
            chunk_processing_batch_results.aggregated_kg_extractions
        )
        connector_aggregated_kg_extractions.entities.update(
            aggregated_batch_extractions.entities
        )
        connector_aggregated_kg_extractions.relationships.update(
            aggregated_batch_extractions.relationships
        )
        connector_aggregated_kg_extractions.terms.update(
            aggregated_batch_extractions.terms
        )

        connector_extraction_stats.append(
            ConnectorExtractionStats(
                connector_id=connector_id,
                num_failed=len(connector_failed_chunk_extractions),
                num_succeeded=len(connector_succeeded_chunk_extractions),
                num_processed=len(processing_chunks),
            )
        )

        processing_chunks = []
        carryover_chunks = []

        connector_aggregated_kg_extractions_list.append(
            connector_aggregated_kg_extractions
        )

    aggregated_kg_extractions = aggregate_kg_extractions(
        connector_aggregated_kg_extractions_list
    )

    for (
        entity,
        extraction_count,
    ) in aggregated_kg_extractions.entities.items():
        if len(entity.split(":")) != 2:
            logger.error(
                f"Invalid entity {entity} in aggregated_kg_extractions.entities"
            )
            continue

        entity_type, entity_name = entity.split(":")
        entity_type = entity_type.upper()
        entity_name = entity_name.capitalize()

        try:
            with get_session_with_current_tenant() as db_session:
                add_entity(
                    db_session=db_session,
                    entity_type=entity_type,
                    name=entity_name,
                    cluster_count=extraction_count,
                )
                db_session.commit()
        except Exception as e:
            logger.error(f"Error adding entity {entity} to the database: {e}")

    relationship_type_counter: dict[str, int] = defaultdict(int)

    for (
        relationship,
        extraction_count,
    ) in aggregated_kg_extractions.relationships.items():
        source_entity, relationship_type, target_entity = relationship.split("__")
        source_entity_general = f"{source_entity.split(':')[0].upper()}"
        target_entity_general = f"{target_entity.split(':')[0].upper()}"
        relationship_type_id_name = (
            f"{source_entity_general}__{relationship_type.lower()}__"
            f"{target_entity_general}"
        )
        relationship_type_counter[relationship_type_id_name] += extraction_count

    for (
        relationship_type_id_name,
        extraction_count,
    ) in relationship_type_counter.items():
        (
            source_entity_type,
            relationship_type,
            target_entity_type,
        ) = relationship_type_id_name.split("__")

        try:
            with get_session_with_current_tenant() as db_session:
                try:
                    add_relationship_type(
                        db_session=db_session,
                        source_entity_type=source_entity_type.upper(),
                        relationship_type=relationship_type,
                        target_entity_type=target_entity_type.upper(),
                        definition=False,
                        extraction_count=extraction_count,
                    )
                    db_session.commit()
                except Exception as e:
                    logger.error(
                        f"Error adding relationship type {relationship_type_id_name} to the database: {e}"
                    )
        except Exception as e:
            logger.error(
                f"Error adding relationship type {relationship_type_id_name} to the database: {e}"
            )

    for (
        relationship,
        extraction_count,
    ) in aggregated_kg_extractions.relationships.items():
        source_entity, relationship_type, target_entity = relationship.split("__")
        source_entity_type = source_entity.split(":")[0]
        target_entity_type = target_entity.split(":")[0]

        try:
            with get_session_with_current_tenant() as db_session:
                add_relationship(db_session, relationship, extraction_count)
                db_session.commit()
        except Exception as e:
            logger.error(
                f"Error adding relationship {relationship} to the database: {e}"
            )

    return connector_extraction_stats


def _kg_chunk_batch_extraction(
    chunks: list[KGChunkFormat],
    index_name: str,
    tenant_id: str,
) -> KGBatchExtractionStats:
    _, fast_llm = get_default_llms()

    succeeded_chunk_id: list[KGChunkId] = []
    failed_chunk_id: list[KGChunkId] = []
    succeeded_chunk_extraction: list[KGChunkExtraction] = []

    preformatted_prompt = MASTER_EXTRACTION_PROMPT.format(
        entity_types=_get_entity_types_str(active=True)
    )

    def process_single_chunk(
        chunk: KGChunkFormat, preformatted_prompt: str
    ) -> tuple[bool, KGUChunkpdateRequest]:
        """Process a single chunk and return success status and chunk ID."""

        # For now, we're just processing the content
        # TODO: Implement actual prompt application logic

        llm_preprocessing = prepare_llm_content(chunk)

        formatted_prompt = preformatted_prompt.replace(
            "---content---", llm_preprocessing.llm_context
        )

        try:
            logger.info(
                f"LLM Extraction from chunk {chunk.chunk_id} from doc {chunk.document_id}"
            )
            raw_extraction_result = fast_llm.invoke(formatted_prompt)
            extraction_result = message_to_string(raw_extraction_result)

            try:
                cleaned_result = (
                    extraction_result.replace("```json", "").replace("```", "").strip()
                )
                parsed_result = json.loads(cleaned_result)
                extracted_entities = parsed_result.get("entities", [])
                extracted_relationships = parsed_result.get("relationships", [])
                extracted_terms = parsed_result.get("terms", [])

                kg_updates = [
                    KGUChunkpdateRequest(
                        doc_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        entities=extracted_entities,
                        relationships=extracted_relationships,
                        terms=extracted_terms,
                    ),
                ]

                update_kg_chunks_vespa_info(
                    kg_update_requests=kg_updates,
                    index_name=index_name,
                    tenant_id=tenant_id,
                )

                logger.info(
                    f"KG updated: {chunk.chunk_id} from doc {chunk.document_id}"
                )

                return True, kg_updates[0]  # only single chunk

            except json.JSONDecodeError as e:
                logger.error(
                    f"Invalid JSON format for extraction of chunk {chunk.chunk_id} \
                             from doc {chunk.document_id}: {str(e)}"
                )
                logger.error(f"Raw output: {extraction_result}")
                return False, KGUChunkpdateRequest(
                    doc_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    entities=set(),
                    relationships=set(),
                    terms=set(),
                )

        except Exception as e:
            logger.error(
                f"Failed to process chunk {chunk.chunk_id} from doc {chunk.document_id}: {str(e)}"
            )
            return False, KGUChunkpdateRequest(
                doc_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                entities=set(),
                relationships=set(),
                terms=set(),
            )

    # Assume for prototype: use_threads = True. TODO: Make thread safe!

    functions_with_args: list[tuple[Callable, tuple]] = [
        (process_single_chunk, (chunk, preformatted_prompt)) for chunk in chunks
    ]

    logger.debug("Running KG extraction on chunks in parallel")
    results = run_functions_tuples_in_parallel(functions_with_args, allow_failures=True)

    # Sort results into succeeded and failed
    for success, chunk_results in results:
        if success:
            succeeded_chunk_id.append(
                KGChunkId(
                    document_id=chunk_results.doc_id, chunk_id=chunk_results.chunk_id
                )
            )
            succeeded_chunk_extraction.append(chunk_results)
        else:
            failed_chunk_id.append(
                KGChunkId(
                    document_id=chunk_results.doc_id, chunk_id=chunk_results.chunk_id
                )
            )

    # Collect data for postgres later on

    aggregated_kg_extractions = KGAggregatedExtractions(
        entities=defaultdict(int),
        relationships=defaultdict(int),
        terms=defaultdict(int),
    )

    for chunk_result in succeeded_chunk_extraction:
        mentioned_chunk_entities: set[str] = set()
        for relationship in chunk_result.relationships:
            relationship_split = relationship.split("__")
            if len(relationship_split) == 3:
                if relationship_split[0] not in mentioned_chunk_entities:
                    aggregated_kg_extractions.entities[relationship_split[0]] += 1
                    mentioned_chunk_entities.add(relationship_split[0])
                if relationship_split[2] not in mentioned_chunk_entities:
                    aggregated_kg_extractions.entities[relationship_split[2]] += 1
                    mentioned_chunk_entities.add(relationship_split[2])
            aggregated_kg_extractions.relationships[relationship] += 1

        for kg_entity in chunk_result.entities:
            if kg_entity not in mentioned_chunk_entities:
                aggregated_kg_extractions.entities[kg_entity] += 1
                mentioned_chunk_entities.add(kg_entity)

        for kg_term in chunk_result.terms:
            aggregated_kg_extractions.terms[kg_term] += 1

    return KGBatchExtractionStats(
        connector_id=chunks[0].connector_id if chunks else None,  # TODO: Update!
        succeeded=succeeded_chunk_id,
        failed=failed_chunk_id,
        aggregated_kg_extractions=aggregated_kg_extractions,
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
