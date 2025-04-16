import json
from collections import defaultdict
from collections.abc import Callable
from typing import cast
from typing import Dict

from langchain_core.messages import HumanMessage

from onyx.db.connector import get_unprocessed_connector_ids
from onyx.db.document import get_document_updated_at
from onyx.db.document import get_unprocessed_kg_documents_for_connector
from onyx.db.document import update_document_kg_info
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import get_entity_types
from onyx.db.relationships import add_or_increment_relationship
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.document_index.vespa.index import KGUChunkUpdateRequest
from onyx.document_index.vespa.index import KGUDocumentUpdateRequest
from onyx.document_index.vespa.kg_interactions import update_kg_chunks_vespa_info
from onyx.kg.models import ConnectorExtractionStats
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGBatchExtractionStats
from onyx.kg.models import KGChunkExtraction
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGChunkId
from onyx.kg.models import KGClassificationContent
from onyx.kg.models import KGClassificationDecisions
from onyx.kg.models import KGClassificationInstructionStrings
from onyx.kg.utils.chunk_preprocessing import prepare_llm_content
from onyx.kg.utils.chunk_preprocessing import prepare_llm_document_content
from onyx.kg.utils.formatting_utils import aggregate_kg_extractions
from onyx.kg.utils.formatting_utils import generalize_entities
from onyx.kg.utils.formatting_utils import generalize_relationships
from onyx.kg.vespa.vespa_interactions import get_document_chunks_for_kg_processing
from onyx.kg.vespa.vespa_interactions import (
    get_document_classification_content_for_kg_processing,
)
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import message_to_string
from onyx.prompts.kg_prompts import MASTER_EXTRACTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def _get_classification_instructions() -> Dict[str, KGClassificationInstructionStrings]:
    """
    Prepare the classification instructions for the given source.
    """

    classification_instructions_dict: Dict[str, KGClassificationInstructionStrings] = {}

    with get_session_with_current_tenant() as db_session:
        entity_types = get_entity_types(db_session, active=None)

    for entity_type in entity_types:
        grounded_source_name = entity_type.grounded_source_name
        if grounded_source_name is None:
            continue
        classification_class_definitions = entity_type.classification_requirements

        classification_options = ", ".join(classification_class_definitions.keys())

        classification_instructions_dict[grounded_source_name] = (
            KGClassificationInstructionStrings(
                classification_options=classification_options,
                classification_class_definitions=classification_class_definitions,
            )
        )

    return classification_instructions_dict


def get_entity_types_str(active: bool | None = None) -> str:
    """
    Get the entity types from the KGChunkExtraction model.
    """

    with get_session_with_current_tenant() as db_session:
        active_entity_types = get_entity_types(db_session, active)

        entity_types_list = []
        for entity_type in active_entity_types:
            if entity_type.description:
                entity_description = "\n  - Description: " + entity_type.description
            else:
                entity_description = ""
            if entity_type.ge_determine_instructions:
                allowed_options = "\n  - Allowed Options: " + ", ".join(
                    entity_type.ge_determine_instructions
                )
            else:
                allowed_options = ""
            entity_types_list.append(
                entity_type.id_name + entity_description + allowed_options
            )

    return "\n".join(entity_types_list)


def get_relationship_types_str(active: bool | None = None) -> str:
    """
    Get the relationship types from the database.

    Args:
        active: Filter by active status (True, False, or None for all)

    Returns:
        A string with all relationship types formatted as "source_type__relationship_type__target_type"
    """
    from onyx.db.relationships import get_all_relationship_types

    with get_session_with_current_tenant() as db_session:
        relationship_types = get_all_relationship_types(db_session)

        # Filter by active status if specified
        if active is not None:
            relationship_types = [
                rt for rt in relationship_types if rt.active == active
            ]

        relationship_types_list = []
        for rel_type in relationship_types:
            # Format as "source_type__relationship_type__target_type"
            formatted_type = f"{rel_type.source_entity_type_id_name}__{rel_type.type}__{rel_type.target_entity_type_id_name}"
            relationship_types_list.append(formatted_type)

    return "\n".join(relationship_types_list)


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

    Approach:
    - Get all unprocessed connectors
    - For each connector:
        - Get all unprocessed documents
        - Classify each document to select proper ones
        - For each document:
            - Get all chunks
            - For each chunk:
                - Extract entities, relationships, and terms
                    - make sure for each entity and relationship also the generalized versions are extracted!
                - Aggregate results as needed
                - Update Vespa and postgres
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")

    with get_session_with_current_tenant() as db_session:
        connector_ids = get_unprocessed_connector_ids(db_session)

    connector_extraction_stats: list[ConnectorExtractionStats] = []
    document_kg_updates: Dict[str, KGUDocumentUpdateRequest] = {}

    processing_chunks: list[KGChunkFormat] = []
    carryover_chunks: list[KGChunkFormat] = []
    connector_aggregated_kg_extractions_list: list[KGAggregatedExtractions] = []

    document_classification_instructions = _get_classification_instructions()

    for connector_id in connector_ids:
        connector_failed_chunk_extractions: list[KGChunkId] = []
        connector_succeeded_chunk_extractions: list[KGChunkId] = []
        connector_aggregated_kg_extractions: KGAggregatedExtractions = (
            KGAggregatedExtractions(
                grounded_entities_document_ids=defaultdict(str),
                entities=defaultdict(int),
                relationships=defaultdict(
                    lambda: defaultdict(int)
                ),  # relationship + source document_id
                terms=defaultdict(int),
            )
        )

        with get_session_with_current_tenant() as db_session:
            unprocessed_documents = get_unprocessed_kg_documents_for_connector(
                db_session,
                connector_id,
            )

            # TODO: restricted for testing only
            unprocessed_documents_list = list(unprocessed_documents)[:2]

        document_classification_content_list = (
            get_document_classification_content_for_kg_processing(
                [
                    unprocessed_document.id
                    for unprocessed_document in unprocessed_documents_list
                ],
                index_name,
                batch_size=processing_chunk_batch_size,
            )
        )

        classification_outcomes: list[tuple[bool, KGClassificationDecisions]] = []

        for document_classification_content in document_classification_content_list:
            classification_outcomes.extend(
                _kg_document_classification(
                    document_classification_content,
                    document_classification_instructions,
                )
            )

        documents_to_process = []
        for document_to_process, document_classification_outcome in zip(
            unprocessed_documents_list, classification_outcomes
        ):
            if (
                document_classification_outcome[0]
                and document_classification_outcome[1].classification_decision
            ):
                documents_to_process.append(document_to_process)

        for document_to_process in documents_to_process:
            formatted_chunk_batches = get_document_chunks_for_kg_processing(
                document_to_process.id,
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
                    # Update grounded_entities_document_ids (replace values)
                    connector_aggregated_kg_extractions.grounded_entities_document_ids.update(
                        aggregated_batch_extractions.grounded_entities_document_ids
                    )
                    # Add to entity counts instead of replacing
                    for entity, count in aggregated_batch_extractions.entities.items():
                        if entity not in connector_aggregated_kg_extractions.entities:
                            connector_aggregated_kg_extractions.entities[entity] = count
                        else:
                            connector_aggregated_kg_extractions.entities[
                                entity
                            ] += count
                    # Add to relationship counts instead of replacing
                    for (
                        relationship,
                        relationship_data,
                    ) in aggregated_batch_extractions.relationships.items():
                        for source_document_id, count in relationship_data.items():
                            if (
                                relationship
                                not in connector_aggregated_kg_extractions.relationships
                            ):
                                connector_aggregated_kg_extractions.relationships[
                                    relationship
                                ] = defaultdict(int)
                            connector_aggregated_kg_extractions.relationships[
                                relationship
                            ][source_document_id] += count

                    # Add to term counts instead of replacing
                    for term, count in aggregated_batch_extractions.terms.items():
                        if term not in connector_aggregated_kg_extractions.terms:
                            connector_aggregated_kg_extractions.terms[term] = count
                        else:
                            connector_aggregated_kg_extractions.terms[term] += count

                    connector_extraction_stats.append(
                        ConnectorExtractionStats(
                            connector_id=connector_id,
                            num_failed=len(connector_failed_chunk_extractions),
                            num_succeeded=len(connector_succeeded_chunk_extractions),
                            num_processed=len(processing_chunks),
                        )
                    )

                    processing_chunks = carryover_chunks.copy()
                    carryover_chunks = []

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
        # Update grounded_entities_document_ids (replace values)
        connector_aggregated_kg_extractions.grounded_entities_document_ids.update(
            aggregated_batch_extractions.grounded_entities_document_ids
        )
        # Add to entity counts instead of replacing
        for entity, count in aggregated_batch_extractions.entities.items():
            if entity not in connector_aggregated_kg_extractions.entities:
                connector_aggregated_kg_extractions.entities[entity] = count
            else:
                connector_aggregated_kg_extractions.entities[entity] += count
        # Add to term counts instead of replacing
        for term, count in aggregated_batch_extractions.terms.items():
            if term not in connector_aggregated_kg_extractions.terms:
                connector_aggregated_kg_extractions.terms[term] = count
            else:
                connector_aggregated_kg_extractions.terms[term] += count

        # Add to relationship counts instead of replacing
        for (
            relationship,
            relationship_data,
        ) in aggregated_batch_extractions.relationships.items():
            for source_document_id, count in relationship_data.items():
                if (
                    relationship
                    not in connector_aggregated_kg_extractions.relationships
                ):
                    connector_aggregated_kg_extractions.relationships[relationship] = (
                        defaultdict(int)
                    )
                connector_aggregated_kg_extractions.relationships[relationship][
                    source_document_id
                ] += count

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

        # aggregate document updates

        for (
            processed_document
        ) in (
            unprocessed_documents_list
        ):  # This will need to change if we do not materialize docs
            document_kg_updates[processed_document.id] = KGUDocumentUpdateRequest(
                document_id=processed_document.id,
                entities=set(),
                relationships=set(),
                terms=set(),
            )

            updated_chunk_batches = get_document_chunks_for_kg_processing(
                processed_document.id,
                index_name,
                batch_size=processing_chunk_batch_size,
            )

            for updated_chunk_batch in updated_chunk_batches:
                for updated_chunk in updated_chunk_batch:
                    chunk_entities = updated_chunk.entities
                    chunk_relationships = updated_chunk.relationships
                    chunk_terms = updated_chunk.terms
                    document_kg_updates[processed_document.id].entities.update(
                        chunk_entities
                    )
                    document_kg_updates[processed_document.id].relationships.update(
                        chunk_relationships
                    )
                    document_kg_updates[processed_document.id].terms.update(chunk_terms)

    aggregated_kg_extractions = aggregate_kg_extractions(
        connector_aggregated_kg_extractions_list
    )

    with get_session_with_current_tenant() as db_session:
        tracked_entity_types = [
            x.id_name for x in get_entity_types(db_session, active=None)
        ]

    # Populate the KG database with the extracted entities, relationships, and terms
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

        if entity_type not in tracked_entity_types:
            continue

        try:
            with get_session_with_current_tenant() as db_session:
                if (
                    entity
                    not in aggregated_kg_extractions.grounded_entities_document_ids
                ):
                    add_entity(
                        db_session=db_session,
                        entity_type=entity_type,
                        name=entity_name,
                        cluster_count=extraction_count,
                    )
                else:
                    event_time = get_document_updated_at(
                        entity,
                        db_session,
                    )
                    add_entity(
                        db_session=db_session,
                        entity_type=entity_type,
                        name=entity_name,
                        cluster_count=extraction_count,
                        document_id=aggregated_kg_extractions.grounded_entities_document_ids[
                            entity
                        ],
                        event_time=event_time,
                    )

                db_session.commit()
        except Exception as e:
            logger.error(f"Error adding entity {entity} to the database: {e}")

    relationship_type_counter: dict[str, int] = defaultdict(int)

    for (
        relationship,
        relationship_data,
    ) in aggregated_kg_extractions.relationships.items():
        for source_document_id, extraction_count in relationship_data.items():
            relationship_split = relationship.split("__")

            source_entity, relationship_type_, target_entity = relationship.split("__")
            source_entity = relationship_split[0]
            relationship_type = " ".join(relationship_split[1:-1]).replace("__", "_")
            target_entity = relationship_split[-1]

            source_entity_type = source_entity.split(":")[0]
            target_entity_type = target_entity.split(":")[0]

            if (
                source_entity_type not in tracked_entity_types
                or target_entity_type not in tracked_entity_types
            ):
                continue

            source_entity_general = f"{source_entity_type.upper()}"
            target_entity_general = f"{target_entity_type.upper()}"
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

        if (
            source_entity_type not in tracked_entity_types
            or target_entity_type not in tracked_entity_types
        ):
            continue

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
        relationship_data,
    ) in aggregated_kg_extractions.relationships.items():
        for source_document_id, extraction_count in relationship_data.items():
            relationship_split = relationship.split("__")

            source_entity, relationship_type_, target_entity = relationship.split("__")
            source_entity = relationship_split[0]
            relationship_type = (
                " ".join(relationship_split[1:-1]).replace("__", " ").replace("_", " ")
            )
            target_entity = relationship_split[-1]

            source_entity_type = source_entity.split(":")[0]
            target_entity_type = target_entity.split(":")[0]

            try:
                with get_session_with_current_tenant() as db_session:
                    add_relationship(
                        db_session, relationship, source_document_id, extraction_count
                    )
                    db_session.commit()
            except Exception as e:
                logger.error(
                    f"Error adding relationship {relationship} to the database: {e}"
                )
                with get_session_with_current_tenant() as db_session:
                    add_or_increment_relationship(
                        db_session, relationship, source_document_id
                    )
                    db_session.commit()

    # Populate the Documents table with the kg information for the documents

    for document_id, document_kg_update in document_kg_updates.items():
        with get_session_with_current_tenant() as db_session:
            update_document_kg_info(
                db_session,
                document_id,
                kg_processed=True,
                kg_data={
                    "entities": list(document_kg_update.entities),
                    "relationships": list(document_kg_update.relationships),
                    "terms": list(document_kg_update.terms),
                },
            )
            db_session.commit()

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
        entity_types=get_entity_types_str(active=True)
    )

    def process_single_chunk(
        chunk: KGChunkFormat, preformatted_prompt: str
    ) -> tuple[bool, KGUChunkUpdateRequest]:
        """Process a single chunk and return success status and chunk ID."""

        # For now, we're just processing the content
        # TODO: Implement actual prompt application logic

        llm_preprocessing = prepare_llm_content(chunk)

        formatted_prompt = preformatted_prompt.replace(
            "---content---", llm_preprocessing.llm_context
        )

        msg = [
            HumanMessage(
                content=formatted_prompt,
            )
        ]

        try:
            logger.info(
                f"LLM Extraction from chunk {chunk.chunk_id} from doc {chunk.document_id}"
            )
            raw_extraction_result = fast_llm.invoke(msg)
            extraction_result = message_to_string(raw_extraction_result)

            try:
                cleaned_result = (
                    extraction_result.replace("```json", "").replace("```", "").strip()
                )
                parsed_result = json.loads(cleaned_result)
                extracted_entities = parsed_result.get("entities", [])
                extracted_relationships = [
                    relationship.replace(" ", "_")
                    for relationship in parsed_result.get("relationships", [])
                ]
                extracted_terms = parsed_result.get("terms", [])

                implied_extracted_relationships = [
                    llm_preprocessing.core_entity + "__" + "mentions" + "__" + entity
                    for entity in extracted_entities
                ]

                all_entities = set(
                    list(extracted_entities)
                    + list(llm_preprocessing.implied_entities)
                    + list(
                        generalize_entities(
                            extracted_entities + llm_preprocessing.implied_entities
                        )
                    )
                )

                logger.info(f"All entities: {all_entities}")

                all_relationships = (
                    extracted_relationships
                    + llm_preprocessing.implied_relationships
                    + implied_extracted_relationships
                )
                all_relationships = list(
                    set(
                        list(all_relationships)
                        + list(generalize_relationships(all_relationships))
                    )
                )

                kg_updates = [
                    KGUChunkUpdateRequest(
                        document_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        core_entity=llm_preprocessing.core_entity,
                        entities=all_entities,
                        relationships=set(all_relationships),
                        terms=set(extracted_terms),
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
                return False, KGUChunkUpdateRequest(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    core_entity=llm_preprocessing.core_entity,
                    entities=set(),
                    relationships=set(),
                    terms=set(),
                )

        except Exception as e:
            logger.error(
                f"Failed to process chunk {chunk.chunk_id} from doc {chunk.document_id}: {str(e)}"
            )
            return False, KGUChunkUpdateRequest(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                core_entity="",
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
                    document_id=chunk_results.document_id,
                    chunk_id=chunk_results.chunk_id,
                )
            )
            succeeded_chunk_extraction.append(chunk_results)
        else:
            failed_chunk_id.append(
                KGChunkId(
                    document_id=chunk_results.document_id,
                    chunk_id=chunk_results.chunk_id,
                )
            )

    # Collect data for postgres later on

    aggregated_kg_extractions = KGAggregatedExtractions(
        grounded_entities_document_ids=defaultdict(str),
        entities=defaultdict(int),
        relationships=defaultdict(
            lambda: defaultdict(int)
        ),  # relationship + source document_id
        terms=defaultdict(int),
    )

    for chunk_result in succeeded_chunk_extraction:
        aggregated_kg_extractions.grounded_entities_document_ids[
            chunk_result.core_entity
        ] = chunk_result.document_id

        mentioned_chunk_entities: set[str] = set()
        for relationship in chunk_result.relationships:
            relationship_split = relationship.split("__")
            if len(relationship_split) == 3:
                source_entity = relationship_split[0]
                target_entity = relationship_split[2]
                if "*" in source_entity or "*" in target_entity:
                    continue
                if source_entity not in mentioned_chunk_entities:
                    aggregated_kg_extractions.entities[source_entity] = 1
                    mentioned_chunk_entities.add(source_entity)
                else:
                    aggregated_kg_extractions.entities[source_entity] += 1
                if target_entity not in mentioned_chunk_entities:
                    aggregated_kg_extractions.entities[target_entity] = 1
                    mentioned_chunk_entities.add(target_entity)
                else:
                    aggregated_kg_extractions.entities[target_entity] += 1
            if relationship not in aggregated_kg_extractions.relationships:
                aggregated_kg_extractions.relationships[relationship] = defaultdict(int)
            aggregated_kg_extractions.relationships[relationship][
                chunk_result.document_id
            ] += 1

        for kg_entity in chunk_result.entities:
            if "*" in kg_entity:
                continue
            if kg_entity not in mentioned_chunk_entities:
                aggregated_kg_extractions.entities[kg_entity] = 1
                mentioned_chunk_entities.add(kg_entity)
            else:
                aggregated_kg_extractions.entities[kg_entity] += 1

        for kg_term in chunk_result.terms:
            if "*" in kg_term:
                continue
            if kg_term not in aggregated_kg_extractions.terms:
                aggregated_kg_extractions.terms[kg_term] = 1
            else:
                aggregated_kg_extractions.terms[kg_term] += 1

    return KGBatchExtractionStats(
        connector_id=chunks[0].connector_id if chunks else None,  # TODO: Update!
        succeeded=succeeded_chunk_id,
        failed=failed_chunk_id,
        aggregated_kg_extractions=aggregated_kg_extractions,
    )


def _kg_document_classification(
    document_classification_content_list: list[KGClassificationContent],
    classification_instructions: dict[str, KGClassificationInstructionStrings],
) -> list[tuple[bool, KGClassificationDecisions]]:
    primary_llm, fast_llm = get_default_llms()

    def classify_single_document(
        document_classification_content: KGClassificationContent,
        classification_instructions: dict[str, KGClassificationInstructionStrings],
    ) -> tuple[bool, KGClassificationDecisions]:
        """Classify a single document whether it should be kg-processed or not"""

        source = document_classification_content.source_type
        document_id = document_classification_content.document_id

        if source not in classification_instructions:
            logger.info(
                f"Source {source} did not have kg classification instructions. No content analysis."
            )
            return False, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=False,
                classification_class=None,
            )

        classification_prompt = prepare_llm_document_content(
            document_classification_content,
            category_list=classification_instructions[source].classification_options,
            category_definitions=classification_instructions[
                source
            ].classification_class_definitions,
        )

        if classification_prompt.llm_prompt is None:
            logger.info(
                f"Source {source} did not have kg document classification instructions. No content analysis."
            )
            return False, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=False,
                classification_class=None,
            )

        msg = [
            HumanMessage(
                content=classification_prompt.llm_prompt,
            )
        ]

        try:
            logger.info(
                f"LLM Classification from document {document_classification_content.document_id}"
            )
            raw_classification_result = primary_llm.invoke(msg)
            classification_result = (
                message_to_string(raw_classification_result)
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            classification_class = classification_result.split("CATEGORY:")[1].strip()

            if (
                classification_class
                in classification_instructions[source].classification_class_definitions
            ):
                extraction_decision = cast(
                    bool,
                    classification_instructions[
                        source
                    ].classification_class_definitions[classification_class][
                        "extraction"
                    ],
                )
            else:
                extraction_decision = False

            return True, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=extraction_decision,
                classification_class=classification_class,
            )
        except Exception as e:
            logger.error(
                f"Failed to classify document {document_classification_content.document_id}: {str(e)}"
            )
            return False, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=False,
                classification_class=None,
            )

    # Assume for prototype: use_threads = True. TODO: Make thread safe!

    functions_with_args: list[tuple[Callable, tuple]] = [
        (
            classify_single_document,
            (document_classification_content, classification_instructions),
        )
        for document_classification_content in document_classification_content_list
    ]

    logger.debug("Running KG classification on documents in parallel")
    results = run_functions_tuples_in_parallel(functions_with_args, allow_failures=True)

    return results


#     logger.debug("Running KG extraction on chunks in parallel")
#     results = run_functions_tuples_in_parallel(functions_with_args, allow_failures=True)

#     # Sort results into succeeded and failed
#     for success, chunk_results in results:
#         if success:
#             succeeded_chunk_id.append(
#                 KGChunkId(
#                     document_id=chunk_results.document_id,
#                     chunk_id=chunk_results.chunk_id,
#                 )
#             )
#             succeeded_chunk_extraction.append(chunk_results)
#         else:
#             failed_chunk_id.append(
#                 KGChunkId(
#                     document_id=chunk_results.document_id,
#                     chunk_id=chunk_results.chunk_id,
#                 )
#             )

#     # Collect data for postgres later on

#     aggregated_kg_extractions = KGAggregatedExtractions(
#         grounded_entities_document_ids=defaultdict(str),
#         entities=defaultdict(int),
#         relationships=defaultdict(int),
#         terms=defaultdict(int),
#     )

#     for chunk_result in succeeded_chunk_extraction:
#         aggregated_kg_extractions.grounded_entities_document_ids[
#             chunk_result.core_entity
#         ] = chunk_result.document_id

#         mentioned_chunk_entities: set[str] = set()
#         for relationship in chunk_result.relationships:
#             relationship_split = relationship.split("__")
#             if len(relationship_split) == 3:
#                 if relationship_split[0] not in mentioned_chunk_entities:
#                     aggregated_kg_extractions.entities[relationship_split[0]] += 1
#                     mentioned_chunk_entities.add(relationship_split[0])
#                 if relationship_split[2] not in mentioned_chunk_entities:
#                     aggregated_kg_extractions.entities[relationship_split[2]] += 1
#                     mentioned_chunk_entities.add(relationship_split[2])
#             aggregated_kg_extractions.relationships[relationship] += 1

#         for kg_entity in chunk_result.entities:
#             if kg_entity not in mentioned_chunk_entities:
#                 aggregated_kg_extractions.entities[kg_entity] += 1
#                 mentioned_chunk_entities.add(kg_entity)

#         for kg_term in chunk_result.terms:
#             aggregated_kg_extractions.terms[kg_term] += 1

#     return KGBatchExtractionStats(
#         connector_id=chunks[0].connector_id if chunks else None,  # TODO: Update!
#         succeeded=succeeded_chunk_id,
#         failed=failed_chunk_id,
#         aggregated_kg_extractions=aggregated_kg_extractions,
#     )


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
