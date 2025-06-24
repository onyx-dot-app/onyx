import json
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from typing import cast

from langchain_core.messages import HumanMessage
from redis.lock import Lock as RedisLock

from onyx.background.celery.tasks.kg_processing.utils import extend_lock
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.db.connector import get_kg_enabled_connectors
from onyx.db.document import get_document_updated_at
from onyx.db.document import get_skipped_kg_documents
from onyx.db.document import get_unprocessed_kg_document_batch_for_connector
from onyx.db.document import update_document_kg_info
from onyx.db.document import update_document_kg_stage
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import delete_from_kg_entities__no_commit
from onyx.db.entities import upsert_staging_entity
from onyx.db.entity_type import get_entity_types
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import KGConfigSettings
from onyx.db.kg_config import validate_kg_settings
from onyx.db.models import Document
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.models import KGStage
from onyx.db.relationships import delete_from_kg_relationships__no_commit
from onyx.db.relationships import upsert_staging_relationship
from onyx.db.relationships import upsert_staging_relationship_type
from onyx.document_index.vespa.index import KGUChunkUpdateRequest
from onyx.kg.models import ConnectorExtractionStats
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGBatchExtractionStats
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGChunkId
from onyx.kg.models import KGClassificationContent
from onyx.kg.models import KGClassificationDecisions
from onyx.kg.models import KGClassificationInstructions
from onyx.kg.models import KGDocumentEntitiesRelationshipsAttributes
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.models import KGEntityTypeInstructions
from onyx.kg.models import KGExtractionInstructions
from onyx.kg.utils.extraction_utils import EntityTypeMetadataTracker
from onyx.kg.utils.extraction_utils import (
    kg_document_entities_relationships_attribute_generation,
)
from onyx.kg.utils.extraction_utils import prepare_llm_content_extraction
from onyx.kg.utils.extraction_utils import prepare_llm_document_content
from onyx.kg.utils.extraction_utils import trackinfo_to_str
from onyx.kg.utils.formatting_utils import aggregate_kg_extractions
from onyx.kg.utils.formatting_utils import extract_relationship_type_id
from onyx.kg.utils.formatting_utils import get_entity_type
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.kg.utils.formatting_utils import make_relationship_type_id
from onyx.kg.utils.formatting_utils import split_entity_id
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.kg.utils.formatting_utils import split_relationship_type_id
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


def _get_classification_extraction_instructions() -> (
    dict[str, dict[str, KGEntityTypeInstructions]]
):
    """
    Prepare the classification instructions for the given source.
    """

    classification_instructions_dict: dict[str, dict[str, KGEntityTypeInstructions]] = (
        {}
    )

    with get_session_with_current_tenant() as db_session:
        entity_types = get_entity_types(db_session, active=True)

    for entity_type in entity_types:
        grounded_source_name = entity_type.grounded_source_name

        if grounded_source_name not in classification_instructions_dict:
            classification_instructions_dict[grounded_source_name] = {}

        if grounded_source_name is None:
            continue

        attributes = entity_type.parsed_attributes
        classification_attributes = attributes.classification_attributes
        classification_options = ", ".join(classification_attributes.keys())
        classification_enabled = (
            len(classification_options) > 0 and len(classification_attributes) > 0
        )

        classification_instructions_dict[grounded_source_name][entity_type.id_name] = (
            KGEntityTypeInstructions(
                metadata_attribute_conversion=attributes.metadata_attribute_conversion,
                classification_instructions=KGClassificationInstructions(
                    classification_enabled=classification_enabled,
                    classification_options=classification_options,
                    classification_class_definitions=classification_attributes,
                ),
                extraction_instructions=KGExtractionInstructions(
                    deep_extraction=entity_type.deep_extraction,
                    active=entity_type.active,
                ),
                filter_instructions=attributes.entity_filter_attributes,
            )
        )

    return classification_instructions_dict


def get_entity_types_str(active: bool | None = None) -> str:
    """
    Get the entity types from the KGChunkExtraction model.
    """

    with get_session_with_current_tenant() as db_session:
        active_entity_types = get_entity_types(db_session, active)

        entity_types_list: list[str] = []
        for entity_type in active_entity_types:
            if entity_type.description:
                entity_description = "\n  - Description: " + entity_type.description
            else:
                entity_description = ""

            if entity_type.entity_values:
                allowed_values = "\n  - Allowed Values: " + ", ".join(
                    entity_type.entity_values
                )
            else:
                allowed_values = ""

            attributes = entity_type.parsed_attributes

            entity_type_attribute_list: list[str] = []
            for attribute, values in attributes.attribute_values.items():
                entity_type_attribute_list.append(
                    f"{attribute}: {trackinfo_to_str(values)}"
                )

            if attributes.classification_attributes:
                entity_type_attribute_list.append(
                    # TODO: restructure classification attribute to be a dict of attribute name to classification info
                    # e.g., {scope: {internal: prompt, external: prompt}, sentiment: {positive: prompt, negative: prompt}}
                    "classification: one of: "
                    + ", ".join(attributes.classification_attributes.keys())
                )
            if entity_type_attribute_list:
                entity_attributes = "\n  - Attributes:\n    - " + "\n    - ".join(
                    entity_type_attribute_list
                )
            else:
                entity_attributes = ""

            entity_types_list.append(
                entity_type.id_name
                + entity_description
                + allowed_values
                + entity_attributes
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
    with get_session_with_current_tenant() as db_session:
        relationship_types = db_session.query(KGRelationshipType).all()

        # Filter by active status if specified

        if active is not None:
            active_relationship_types = cast(
                list[KGRelationshipType] | list[KGRelationshipTypeExtractionStaging],
                [rt for rt in relationship_types if rt.active == active],
            )
        else:
            active_relationship_types = cast(
                list[KGRelationshipType] | list[KGRelationshipTypeExtractionStaging],
                relationship_types,
            )

        relationship_types_list = []
        for rel_type in active_relationship_types:
            # Format as "source_type__relationship_type__target_type"
            formatted_type = make_relationship_type_id(
                rel_type.source_entity_type_id_name,
                rel_type.type,
                rel_type.target_entity_type_id_name,
            )
            relationship_types_list.append(formatted_type)

    return "\n".join(relationship_types_list)


def _get_batch_metadata(
    unprocessed_document_batch: list[Document],
    connector_source: str,
    source_type_classification_extraction_instructions: dict[
        str, KGEntityTypeInstructions
    ],
    index_name: str,
    kg_config_settings: KGConfigSettings,
    processing_chunk_batch_size: int,
) -> dict[str, KGEnhancedDocumentMetadata]:
    """
    Get the entity types for the given unprocessed documents.
    """

    kg_document_meta_data_dict: dict[str, KGEnhancedDocumentMetadata] = {
        document.id: KGEnhancedDocumentMetadata(
            entity_type=None,
            metadata_attribute_conversion=None,
            document_metadata=None,
            deep_extraction=False,
            classification_enabled=False,
            classification_instructions=None,
            skip=True,
        )
        for document in unprocessed_document_batch
    }

    if len(source_type_classification_extraction_instructions) == 1:
        batch_entity = list(source_type_classification_extraction_instructions.keys())[
            0
        ]  # does source only have one entity type?
    else:
        batch_entity = None

    # the documents can be of multiple entity types. We need to identify the entity type for each document

    first_chunk_generator = get_document_classification_content_for_kg_processing(
        [
            unprocessed_document.id
            for unprocessed_document in unprocessed_document_batch
        ],
        batch_size=processing_chunk_batch_size,
    )

    for first_chunk_list in first_chunk_generator:
        for first_chunk in first_chunk_list:

            document_id = first_chunk.document_id
            doc_entity = None
            found_current_entity_type = False

            if not isinstance(document_id, str):
                continue

            chunk_metadata = first_chunk.source_metadata

            if batch_entity:
                doc_entity = batch_entity
                found_current_entity_type = True
            else:

                if not chunk_metadata:
                    continue

                for (
                    potential_entity_type
                ) in source_type_classification_extraction_instructions.keys():
                    potential_entity_type_attribute_filters = (
                        source_type_classification_extraction_instructions[
                            potential_entity_type
                        ].filter_instructions
                        or {}
                    )

                    if not potential_entity_type_attribute_filters:
                        continue

                    if all(
                        chunk_metadata.get(attribute)
                        == potential_entity_type_attribute_filters.get(attribute)
                        for attribute in potential_entity_type_attribute_filters
                    ):
                        doc_entity = potential_entity_type
                        found_current_entity_type = True
                        break

            if found_current_entity_type:
                assert isinstance(doc_entity, str)
                kg_document_meta_data_dict[document_id].entity_type = doc_entity
                kg_document_meta_data_dict[
                    document_id
                ].metadata_attribute_conversion = source_type_classification_extraction_instructions[
                    doc_entity
                ].metadata_attribute_conversion
                entity_instructions = (
                    source_type_classification_extraction_instructions[doc_entity]
                )

                kg_document_meta_data_dict[document_id].document_metadata = (
                    chunk_metadata
                )
                kg_document_meta_data_dict[document_id].classification_enabled = (
                    entity_instructions.classification_instructions.classification_enabled
                )
                kg_document_meta_data_dict[document_id].classification_instructions = (
                    entity_instructions.classification_instructions
                )
                kg_document_meta_data_dict[document_id].deep_extraction = (
                    entity_instructions.extraction_instructions.deep_extraction
                )
                kg_document_meta_data_dict[document_id].skip = False

    return kg_document_meta_data_dict


def kg_extraction(
    tenant_id: str,
    index_name: str,
    lock: RedisLock,
    processing_chunk_batch_size: int = 8,
) -> list[ConnectorExtractionStats]:
    """
    This extraction will try to extract from all chunks that have not been kg-processed yet.

    Approach:
    - Get all connectors that are enabled for KG extraction
    - For each enabled connector:
        - Get unprocessed documents (using a generator)
        - For each batch of unprocessed documents:
            - Classify each document to select proper ones
            - Get and extract from chunks
            - Update chunks in Vespa
            - Update temporary KG extraction tables
            - Update document table to set kg_extracted = True
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")

    kg_config_settings = get_kg_config_settings()
    validate_kg_settings(kg_config_settings)

    # get connector ids that are enabled for KG extraction

    with get_session_with_current_tenant() as db_session:
        kg_enabled_connectors = get_kg_enabled_connectors(db_session)

    connector_extraction_stats: list[ConnectorExtractionStats] = []

    processing_chunk_doc_extractions: list[
        tuple[KGChunkFormat, KGDocumentEntitiesRelationshipsAttributes]
    ] = []
    connector_aggregated_kg_extractions_list: list[KGAggregatedExtractions] = []

    document_classification_extraction_instructions = (
        _get_classification_extraction_instructions()
    )
    with get_session_with_current_tenant() as db_session:
        active_entity_type_names = {
            entity_type.id_name
            for entity_type in get_entity_types(db_session, active=True)
        }

    # Track which metadata attributes are possible for each entity type
    metadata_tracker = EntityTypeMetadataTracker()
    metadata_tracker.import_typeinfo()

    last_lock_time = time.monotonic()

    # Iterate over connectors that are enabled for KG extraction

    for kg_enabled_connector in kg_enabled_connectors:
        connector_id = kg_enabled_connector.id
        connector_coverage_days = kg_enabled_connector.kg_coverage_days
        connector_source = kg_enabled_connector.source
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

        document_batch_counter = 0

        # iterate over un-kg-processed documents in connector
        while True:

            # TODO: restructure using various functions

            # get a batch of unprocessed documents
            with get_session_with_current_tenant() as db_session:
                unprocessed_document_batch = (
                    get_unprocessed_kg_document_batch_for_connector(
                        db_session,
                        connector_id,
                        kg_coverage_start=kg_config_settings.KG_COVERAGE_START_DATE,
                        kg_max_coverage_days=connector_coverage_days
                        or kg_config_settings.KG_MAX_COVERAGE_DAYS,
                        batch_size=8,
                    )
                )

            if len(unprocessed_document_batch) == 0:
                logger.info(
                    f"No unprocessed documents found for connector {connector_id}. Processed {document_batch_counter} batches."
                )
                break

            document_batch_counter += 1
            last_lock_time = extend_lock(
                lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
            )

            connector_extraction_stats = []
            connector_aggregated_kg_extractions_list = []
            connector_failed_chunk_extractions = []
            connector_succeeded_chunk_extractions = []
            connector_aggregated_kg_extractions = KGAggregatedExtractions(
                grounded_entities_document_ids=defaultdict(str),
                entities=defaultdict(int),
                relationships=defaultdict(
                    lambda: defaultdict(int)
                ),  # relationship + source document_id
                terms=defaultdict(int),
            )

            logger.info(f"Processing document batch {document_batch_counter}")

            # First, identify which entity we are processing for each document
            entity_type_instructions = (
                document_classification_extraction_instructions.get(
                    connector_source, {}
                )
            )
            batch_metadata: dict[str, KGEnhancedDocumentMetadata] = _get_batch_metadata(
                unprocessed_document_batch,
                connector_source,
                entity_type_instructions,
                index_name,
                kg_config_settings,
                processing_chunk_batch_size,
            )  # need doc attributes, entity type, and various instructions

            # mark docs in unprocessed_document_batch as EXTRACTING
            for unprocessed_document in unprocessed_document_batch:
                if batch_metadata[unprocessed_document.id].entity_type is None:
                    # info for after the connector has been processed
                    kg_stage = KGStage.SKIPPED
                    logger.debug(
                        f"Document {unprocessed_document.id} is not of any entity type"
                    )
                elif batch_metadata[unprocessed_document.id].skip:
                    # info for after the connector has been processed. But no message as there may be many
                    # purposefully skipped documents
                    kg_stage = KGStage.SKIPPED
                else:
                    kg_stage = KGStage.EXTRACTING

                with get_session_with_current_tenant() as db_session:
                    update_document_kg_stage(
                        db_session,
                        unprocessed_document.id,
                        kg_stage,
                    )

                    if kg_stage == KGStage.EXTRACTING:
                        delete_from_kg_relationships__no_commit(
                            db_session, [unprocessed_document.id]
                        )
                        delete_from_kg_entities__no_commit(
                            db_session, [unprocessed_document.id]
                        )
                    db_session.commit()

            # Iterate over batches of unprocessed files
            # For each batch:
            #   - Classify documents
            #   - Get and analyze batches of chunks
            #   - Store results in postgres:
            #      - entities and relationships in temp kg extraction tables
            #      - document classification in temp kg entity extraction table
            #      - set kg_stage = extracted in document table

            classification_outcomes: list[tuple[bool, KGClassificationDecisions]] = []
            documents_to_process: list[str] = []
            document_classifications: dict[str, KGClassificationDecisions | None] = {}

            # run this only for primary grounded sources that have a classification approach configured

            # get documents with classification enabled
            classification_batch_list = []
            for unprocessed_document in unprocessed_document_batch:
                # generate document batch for classifications
                if (
                    batch_metadata[unprocessed_document.id].classification_enabled
                    and batch_metadata[unprocessed_document.id].deep_extraction
                ):
                    classification_batch_list.append(unprocessed_document.id)

            # TODO: revisit in deep extraction. Should probably happen inside process_batch_extraction
            # document_classification_content_generator = (
            #     get_document_classification_content_for_kg_processing(
            #         document_ids=classification_batch_list,
            #         kg_config_settings=kg_config_settings,
            #         batch_size=processing_chunk_batch_size,
            #         entity_type=batch_metadata[unprocessed_document.id].entity_type,
            #     )
            # )

            # # Document classification
            # #    - Decide whether a document should be processed or ignored, and
            # #    - Store document type in postgres later

            classification_outcomes = []
            # try:
            #     for (
            #         generated_doc_classification_content_list
            #     ) in document_classification_content_generator:
            #         doc_ids = [
            #             content.document_id
            #             for content in generated_doc_classification_content_list
            #         ]
            #         batch_classification_instructions = {}
            #         for doc_id in doc_ids:
            #             if doc_id in batch_metadata:
            #                 batch_classification_instructions[doc_id] = batch_metadata[
            #                     doc_id
            #                 ].classification_instructions
            #             else:
            #                 batch_classification_instructions[doc_id] = None
            #         classification_outcomes.extend(
            #             _kg_document_classification(
            #                 generated_doc_classification_content_list,
            #                 batch_classification_instructions,
            #                 kg_config_settings,
            #             )
            #         )
            # except Exception as e:
            #     logger.error(f"Error in document classification: {e}")
            #     raise e

            # collect documents to process in batch and capture classification results

            documents_to_process = [x.id for x in unprocessed_document_batch]

            for document_classification_outcome in classification_outcomes:
                if (
                    document_classification_outcome[0]
                    and document_classification_outcome[1].classification_decision
                ):
                    document_classification_result: KGClassificationDecisions | None = (
                        document_classification_outcome[1]
                    )
                    if document_classification_result:
                        document_classifications[
                            document_classification_result.document_id
                        ] = document_classification_result

                else:
                    documents_to_process.remove(
                        document_classification_outcome[1].document_id
                    )

            for unprocessed_document in unprocessed_document_batch:
                if (
                    unprocessed_document.id not in documents_to_process
                    or batch_metadata[unprocessed_document.id].entity_type is None
                    or batch_metadata[unprocessed_document.id].skip
                ):
                    with get_session_with_current_tenant() as db_session:
                        update_document_kg_stage(
                            db_session,
                            unprocessed_document.id,
                            KGStage.SKIPPED,
                        )
                        db_session.commit()
                    continue

                # 1. perform (implicit) KG 'extractions' on the documents that should be processed
                # This is really about assigning document meta-data to KG entities/relationships or KG entity attributes
                # General approach:
                #    - vendor emails to Employee-type entities + relationship to current primary grounded entity
                #    - external account emails to Account-type entities + relationship to current primary grounded entity
                #    - non-email owners to KG current entity's attributes, no relationships
                # We also collect email addresses of vendors and external accounts to inform chunk processing

                kg_document_extractions = (
                    kg_document_entities_relationships_attribute_generation(
                        unprocessed_document,
                        batch_metadata[unprocessed_document.id],
                        active_entity_type_names,
                        kg_config_settings,
                    )
                )

                # 2. process each chunk in the document
                # TODO: revisit once deep extraction is implemented, or metadata is different per chunk
                # for now, just grab a single chunk (could be any chunk, as metadata is the same) per document
                formatted_chunk_batches = get_document_chunks_for_kg_processing(
                    document_id=unprocessed_document.id,
                    deep_extraction=batch_metadata[
                        unprocessed_document.id
                    ].deep_extraction,
                    index_name=index_name,
                    tenant_id=tenant_id,
                    batch_size=1,
                )

                formatted_chunk_doc_batch = next(formatted_chunk_batches)
                if not formatted_chunk_doc_batch:
                    continue

                processing_chunk_doc_extractions.extend(
                    [
                        (chunk, kg_document_extractions)
                        for chunk in formatted_chunk_doc_batch
                    ]
                )

            # processes chunks
            chunk_processing_batch_results = _kg_chunk_batch_extraction(
                chunk_doc_extractions=processing_chunk_doc_extractions,
                kg_config_settings=kg_config_settings,
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
                for source_document_id, extraction_count in relationship_data.items():
                    if (
                        relationship
                        not in connector_aggregated_kg_extractions.relationships
                    ):
                        connector_aggregated_kg_extractions.relationships[
                            relationship
                        ] = defaultdict(int)
                    connector_aggregated_kg_extractions.relationships[relationship][
                        source_document_id
                    ] += extraction_count

            connector_extraction_stats.append(
                ConnectorExtractionStats(
                    connector_id=connector_id,
                    num_failed=len(connector_failed_chunk_extractions),
                    num_succeeded=len(connector_succeeded_chunk_extractions),
                    num_processed=len(processing_chunk_doc_extractions),
                )
            )

            processing_chunk_doc_extractions = []

            connector_aggregated_kg_extractions_list.append(
                connector_aggregated_kg_extractions
            )

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
                parts = split_entity_id(entity)
                if len(parts) != 2:
                    logger.error(
                        f"Invalid entity {entity} in aggregated_kg_extractions.entities"
                    )
                    continue

                entity_type, entity_name = parts
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
                            # Ungrounded entities
                            upsert_staging_entity(
                                db_session=db_session,
                                name=entity_name,
                                entity_type=entity_type,
                                occurrences=extraction_count,
                            )
                        else:
                            # Primary grounded entities
                            event_time = get_document_updated_at(
                                entity,
                                db_session,
                            )

                            document_id = aggregated_kg_extractions.grounded_entities_document_ids[
                                entity
                            ]

                            entity_attributes: dict[str, Any] | None = batch_metadata[
                                document_id
                            ].document_metadata

                            if entity_attributes:
                                entity_attributes = entity_attributes.copy()
                            else:
                                entity_attributes = {}

                            if document_id in document_classifications:
                                document_classification_result = (
                                    document_classifications[document_id]
                                )
                            else:
                                document_classification_result = None

                            if document_classification_result:

                                if document_classification_result.classification_class:
                                    entity_attributes["classification_type"] = (
                                        document_classification_result.classification_class
                                    )

                            # only keep selected attributes (and translate the attribute names)
                            metadata_attributes = entity_type_instructions[
                                entity_type
                            ].metadata_attribute_conversion
                            keep_attributes = {
                                metadata_attributes[attr_name].name: attr_val
                                for attr_name, attr_val in entity_attributes.items()
                                if (
                                    attr_name in metadata_attributes
                                    and metadata_attributes[attr_name].keep
                                )
                            }

                            upserted_entity = upsert_staging_entity(
                                db_session=db_session,
                                name=entity_name,
                                entity_type=entity_type,
                                document_id=document_id,
                                occurrences=extraction_count,
                                attributes=keep_attributes,
                                event_time=event_time,
                            )
                            metadata_tracker.track_metadata(
                                entity_type, upserted_entity.attributes
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
                    relationship_split = split_relationship_id(relationship)

                    if len(relationship_split) != 3:
                        logger.error(
                            f"Invalid relationship {relationship} in aggregated_kg_extractions.relationships"
                        )
                        continue

                    source_entity, relationship_type, target_entity = relationship_split

                    source_entity_type = get_entity_type(source_entity)
                    target_entity_type = get_entity_type(target_entity)

                    if (
                        source_entity_type not in tracked_entity_types
                        or target_entity_type not in tracked_entity_types
                    ):
                        continue

                    relationship_type_id_name = extract_relationship_type_id(
                        relationship
                    )
                    relationship_type_counter[
                        relationship_type_id_name
                    ] += extraction_count

            for (
                relationship_type_id_name,
                extraction_count,
            ) in relationship_type_counter.items():
                (
                    source_entity_type,
                    relationship_type,
                    target_entity_type,
                ) = split_relationship_type_id(relationship_type_id_name)

                if (
                    source_entity_type not in tracked_entity_types
                    or target_entity_type not in tracked_entity_types
                ):
                    continue

                with get_session_with_current_tenant() as db_session:
                    try:
                        upsert_staging_relationship_type(
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
            for (
                relationship,
                relationship_data,
            ) in aggregated_kg_extractions.relationships.items():
                for source_document_id, extraction_count in relationship_data.items():
                    relationship_split = split_relationship_id(relationship)

                    if len(relationship_split) != 3:
                        logger.error(
                            f"Invalid relationship {relationship} in aggregated_kg_extractions.relationships"
                        )
                        continue

                    source_entity, relationship_type, target_entity = (
                        split_relationship_id(relationship)
                    )
                    source_entity_type = get_entity_type(source_entity)
                    target_entity_type = get_entity_type(target_entity)

                    with get_session_with_current_tenant() as db_session:
                        try:
                            upsert_staging_relationship(
                                db_session=db_session,
                                relationship_id_name=relationship,
                                source_document_id=source_document_id,
                                occurrences=extraction_count,
                            )
                            db_session.commit()
                        except Exception as e:
                            logger.error(
                                f"Error adding relationship {relationship} to the database: {e}"
                            )

            # Populate the Documents table with the kg information for the documents

            for processed_document in documents_to_process:
                with get_session_with_current_tenant() as db_session:
                    update_document_kg_info(
                        db_session,
                        processed_document,
                        KGStage.EXTRACTED,
                    )
                    db_session.commit()

            # Update the document table
            for classification_outcome in classification_outcomes:
                if not classification_outcome[0]:
                    with get_session_with_current_tenant() as db_session:
                        update_document_kg_stage(
                            db_session,
                            classification_outcome[1].document_id,
                            KGStage.DO_NOT_EXTRACT,
                        )
                        db_session.commit()
                    continue
                classification_result = classification_outcome[1]
                if classification_result.classification_decision:
                    document_id = classification_result.document_id
                    kg_stage = KGStage.EXTRACTED

                else:
                    kg_stage = KGStage.SKIPPED

                with get_session_with_current_tenant() as db_session:
                    update_document_kg_stage(
                        db_session,
                        classification_outcome[1].document_id,
                        kg_stage,
                    )
                    db_session.commit()

        # Update the the Skipped Docs back to Not Started in

        with get_session_with_current_tenant() as db_session:
            skipped_documents = get_skipped_kg_documents(db_session)
            for document_id in skipped_documents:
                update_document_kg_stage(
                    db_session,
                    document_id,
                    KGStage.NOT_STARTED,
                )
                db_session.commit()

    metadata_tracker.export_typeinfo()
    return connector_extraction_stats


# TODO: this only needs to run if deep extraction is true with some refactoring in
# kg_extraction to use the KGDocumentEntitiesRelationshipsAttributes to create the
# staging objects
# this will also allow us to move the KGChunkFormat extraction inside this function,
# removing the need for slow vespa querying for non-deep extraction chunks
def _kg_chunk_batch_extraction(
    chunk_doc_extractions: list[
        tuple[KGChunkFormat, KGDocumentEntitiesRelationshipsAttributes]
    ],
    kg_config_settings: KGConfigSettings,
) -> KGBatchExtractionStats:
    _, fast_llm = get_default_llms()

    succeeded_chunk_id: list[KGChunkId] = []
    failed_chunk_id: list[KGChunkId] = []
    succeeded_chunk_extraction: list[KGUChunkUpdateRequest] = []

    def process_single_chunk(
        chunk_doc_extraction: tuple[
            KGChunkFormat, KGDocumentEntitiesRelationshipsAttributes
        ],
        preformatted_prompt: str,
        kg_config_settings: KGConfigSettings,
    ) -> tuple[bool, KGUChunkUpdateRequest]:
        """Process a single chunk and return update request and other important KG processing information"""

        # Chunk treatment variables

        chunk, kg_document_extractions = chunk_doc_extraction
        chunk_needs_deep_extraction = chunk.deep_extraction

        company_participant_emails = kg_document_extractions.company_participant_emails
        account_participant_emails = kg_document_extractions.account_participant_emails

        # Initialize common variables
        deep_extracted_entities: list[str] = []
        deep_extracted_relationships: list[str] = []
        deep_implied_extracted_relationships: list[str] = []
        deep_extracted_terms: list[str] = []

        if chunk_needs_deep_extraction:
            llm_context = prepare_llm_content_extraction(
                chunk,
                company_participant_emails,
                account_participant_emails,
                kg_config_settings,
            )

            formatted_prompt = MASTER_EXTRACTION_PROMPT.replace(
                "---content---", llm_context
            )

            msg = [
                HumanMessage(
                    content=formatted_prompt,
                )
            ]

            logger.info(
                f"LLM Extraction from chunk {chunk.chunk_id} from doc {chunk.document_id}"
            )

            try:
                raw_extraction_result = fast_llm.invoke(msg)
                extraction_result = message_to_string(raw_extraction_result)
                cleaned_result = (
                    extraction_result.replace("```json", "").replace("```", "").strip()
                )
                parsed_result = json.loads(cleaned_result)

                deep_extracted_entities = parsed_result.get("entities", [])
                deep_extracted_relationships = [
                    relationship.replace(" ", "_")
                    for relationship in parsed_result.get("relationships", [])
                ]
                deep_extracted_terms = parsed_result.get("terms", [])
            except Exception as e:
                logger.error(
                    f"Failed to process chunk {chunk.chunk_id} from doc {chunk.document_id}: {str(e)}"
                )
                return False, KGUChunkUpdateRequest(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    core_entity=kg_document_extractions.kg_core_document_id_name,
                    entities=set(),
                    relationships=set(),
                    terms=set(),
                )

        deep_implied_extracted_relationships = [
            make_relationship_id(
                kg_document_extractions.kg_core_document_id_name,
                "mentions",
                extracted_entity,
            )
            for extracted_entity in deep_extracted_entities
        ]

        all_entities = set(
            list(deep_extracted_entities)
            + list(kg_document_extractions.implied_entities)
        )

        all_relationships = (
            list(deep_extracted_relationships)
            + list(kg_document_extractions.implied_relationships)
            + deep_implied_extracted_relationships
        )
        all_relationships = list(set(all_relationships))

        # Add vendor relationship if no relationship established yet

        if not all_relationships:
            all_relationships.append(
                make_relationship_id(
                    make_entity_id("VENDOR", cast(str, kg_config_settings.KG_VENDOR)),
                    "relates_to",
                    kg_document_extractions.kg_core_document_id_name,
                )
            )

        logger.info(f"KG extracted: doc {chunk.document_id} chunk {chunk.chunk_id}")
        return True, KGUChunkUpdateRequest(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            core_entity=kg_document_extractions.kg_core_document_id_name,
            entities=all_entities,
            relationships=set(all_relationships),
            terms=set(deep_extracted_terms),
        )

    # Assume for prototype: use_threads = True. TODO: Make thread safe!

    functions_with_args: list[tuple[Callable, tuple]] = [
        (process_single_chunk, (chunk_doc_extraction, "", kg_config_settings))
        for chunk_doc_extraction in chunk_doc_extractions
    ]

    logger.debug("Running KG extraction on chunks in parallel")
    results = run_functions_tuples_in_parallel(functions_with_args, allow_failures=True)

    # Sort results into succeeded and failed
    for success, chunk_results in results:

        chunk_structure = KGChunkId(
            document_id=chunk_results.document_id,
            chunk_id=chunk_results.chunk_id,
        )

        if success:
            succeeded_chunk_id.append(chunk_structure)
            succeeded_chunk_extraction.append(chunk_results)
        else:
            failed_chunk_id.append(chunk_structure)

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
        for relationship in chunk_result.relationships or set():
            relationship_split = split_relationship_id(relationship)
            if len(relationship_split) == 3:
                source_entity = relationship_split[0]
                target_entity = relationship_split[2]
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

        for kg_entity in chunk_result.entities or set():
            if kg_entity not in mentioned_chunk_entities:
                aggregated_kg_extractions.entities[kg_entity] = 1
                mentioned_chunk_entities.add(kg_entity)
            else:
                aggregated_kg_extractions.entities[kg_entity] += 1

        for kg_term in chunk_result.terms or set():
            if kg_term not in aggregated_kg_extractions.terms:
                aggregated_kg_extractions.terms[kg_term] = 1
            else:
                aggregated_kg_extractions.terms[kg_term] += 1

    return KGBatchExtractionStats(
        connector_id=(
            chunk_doc_extractions[0][0].connector_id if chunk_doc_extractions else None
        ),  # All have same connector_id
        succeeded=succeeded_chunk_id,
        failed=failed_chunk_id,
        aggregated_kg_extractions=aggregated_kg_extractions,
    )


def _kg_document_classification(
    document_classification_content_list: list[KGClassificationContent],
    classification_extraction_instructions: dict[
        str, KGClassificationInstructions | None
    ],
    kg_config_settings: KGConfigSettings,
) -> list[tuple[bool, KGClassificationDecisions]]:
    primary_llm, fast_llm = get_default_llms()

    def classify_single_document(
        document_classification_content: KGClassificationContent,
        document_classification_extraction_instructions: KGClassificationInstructions,
        kg_config_settings: KGConfigSettings,
    ) -> tuple[bool, KGClassificationDecisions]:
        """Classify a single document whether it should be kg-processed or not"""

        source = document_classification_content.source_type
        document_id = document_classification_content.document_id

        classification_prompt = prepare_llm_document_content(
            document_classification_content,
            category_list=document_classification_extraction_instructions.classification_options,
            category_definitions=document_classification_extraction_instructions.classification_class_definitions,
            kg_config_settings=kg_config_settings,
        )

        if classification_prompt.llm_prompt is None:
            logger.info(
                f"Source {source} did not have kg document classification instructions. No content analysis."
            )
            return False, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=False,
                classification_class=None,
                source_metadata=document_classification_content.source_metadata,
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
                in document_classification_extraction_instructions.classification_class_definitions
            ):
                extraction_decision = document_classification_extraction_instructions.classification_class_definitions[
                    classification_class
                ].extraction
            else:
                extraction_decision = False

            return True, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=extraction_decision,
                classification_class=classification_class,
                source_metadata=document_classification_content.source_metadata,
            )
        except Exception as e:
            logger.error(
                f"Failed to classify document {document_classification_content.document_id}: {str(e)}"
            )
            return False, KGClassificationDecisions(
                document_id=document_id,
                classification_decision=False,
                classification_class=None,
                source_metadata=document_classification_content.source_metadata,
            )

    # Assume for prototype: use_threads = True. TODO: Make thread safe!

    functions_with_args: list[tuple[Callable, tuple]] = [
        (
            classify_single_document,
            (
                document_classification_content,
                classification_extraction_instructions[
                    document_classification_content.document_id
                ],
                kg_config_settings,
            ),
        )
        for document_classification_content in document_classification_content_list
    ]

    logger.debug("Running KG classification on documents in parallel")
    results = run_functions_tuples_in_parallel(functions_with_args, allow_failures=True)

    return results
