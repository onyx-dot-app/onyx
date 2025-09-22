import time
from typing import Any

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
from onyx.db.kg_config import validate_kg_settings
from onyx.db.models import Document
from onyx.db.models import KGStage
from onyx.db.relationships import delete_from_kg_relationships__no_commit
from onyx.db.relationships import upsert_staging_relationship
from onyx.db.relationships import upsert_staging_relationship_type
from onyx.kg.models import KGClassificationInstructions
from onyx.kg.models import KGDocumentDeepExtractionResults
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.models import KGEntityTypeInstructions
from onyx.kg.models import KGExtractionInstructions
from onyx.kg.models import KGImpliedExtractionResults
from onyx.kg.utils.extraction_utils import EntityTypeMetadataTracker
from onyx.kg.utils.extraction_utils import (
    get_batch_documents_metadata,
)
from onyx.kg.utils.extraction_utils import kg_deep_extraction
from onyx.kg.utils.extraction_utils import (
    kg_implied_extraction,
)
from onyx.kg.utils.formatting_utils import extract_relationship_type_id
from onyx.kg.utils.formatting_utils import get_entity_type
from onyx.kg.utils.formatting_utils import split_entity_id
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def _get_classification_extraction_instructions() -> (
    dict[str | None, dict[str, KGEntityTypeInstructions]]
):
    """
    Prepare the classification instructions for the given source.
    """

    classification_instructions_dict: dict[
        str | None, dict[str, KGEntityTypeInstructions]
    ] = {}

    with get_session_with_current_tenant() as db_session:
        entity_types = get_entity_types(db_session, active=True)

    for entity_type in entity_types:
        grounded_source_name = entity_type.grounded_source_name

        if grounded_source_name not in classification_instructions_dict:
            classification_instructions_dict[grounded_source_name] = {}

        if grounded_source_name is None:
            continue

        attributes = entity_type.parsed_attributes
        classification_attributes = {
            option: info
            for option, info in attributes.classification_attributes.items()
            if info.extraction
        }
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
                entity_filter_attributes=attributes.entity_filter_attributes,
            )
        )

    return classification_instructions_dict


def _get_batch_documents_enhanced_metadata(
    unprocessed_document_batch: list[Document],
    source_type_classification_extraction_instructions: dict[
        str, KGEntityTypeInstructions
    ],
    connector_source: str,
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

    batch_entity = None
    if len(source_type_classification_extraction_instructions) == 1:
        # if source only has one entity type, the document must be of that type
        batch_entity = list(source_type_classification_extraction_instructions.keys())[
            0
        ]

    # the documents can be of multiple entity types. We need to identify the entity type for each document
    batch_metadata = get_batch_documents_metadata(
        [
            unprocessed_document.id
            for unprocessed_document in unprocessed_document_batch
        ],
        connector_source,
    )

    for metadata in batch_metadata:
        document_id = metadata.document_id
        doc_entity = None

        if not isinstance(document_id, str):
            continue

        chunk_metadata = metadata.source_metadata

        if batch_entity:
            doc_entity = batch_entity
        else:
            # TODO: make this a helper function
            if not chunk_metadata:
                continue

            for (
                potential_entity_type
            ) in source_type_classification_extraction_instructions.keys():
                potential_entity_type_attribute_filters = (
                    source_type_classification_extraction_instructions[
                        potential_entity_type
                    ].entity_filter_attributes
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
                    break

        if doc_entity is None:
            continue

        entity_instructions = source_type_classification_extraction_instructions[
            doc_entity
        ]

        kg_document_meta_data_dict[document_id] = KGEnhancedDocumentMetadata(
            entity_type=doc_entity,
            metadata_attribute_conversion=(
                source_type_classification_extraction_instructions[
                    doc_entity
                ].metadata_attribute_conversion
            ),
            document_metadata=chunk_metadata,
            deep_extraction=entity_instructions.extraction_instructions.deep_extraction,
            classification_enabled=entity_instructions.classification_instructions.classification_enabled,
            classification_instructions=entity_instructions.classification_instructions,
            skip=False,
        )

    return kg_document_meta_data_dict


def kg_extraction(
    tenant_id: str,
    index_name: str,
    lock: RedisLock,
    processing_chunk_batch_size: int = 8,
) -> None:
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

    document_classification_extraction_instructions = (
        _get_classification_extraction_instructions()
    )

    # get entity type info
    with get_session_with_current_tenant() as db_session:
        all_entity_types = get_entity_types(db_session)
        active_entity_types = {
            entity_type.id_name
            for entity_type in get_entity_types(db_session, active=True)
        }

        # entity_type: (metadata: conversion property)
        entity_metadata_conversion_instructions = {
            entity_type.id_name: entity_type.parsed_attributes.metadata_attribute_conversion
            for entity_type in all_entity_types
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

        document_batch_counter = 0

        # iterate over un-kg-processed documents in connector
        while True:
            # get a batch of unprocessed documents
            with get_session_with_current_tenant() as db_session:
                unprocessed_document_batch = (
                    get_unprocessed_kg_document_batch_for_connector(
                        db_session,
                        connector_id,
                        kg_coverage_start=kg_config_settings.KG_COVERAGE_START_DATE,
                        kg_max_coverage_days=connector_coverage_days
                        or kg_config_settings.KG_MAX_COVERAGE_DAYS,
                        batch_size=processing_chunk_batch_size,
                    )
                )

            if len(unprocessed_document_batch) == 0:
                logger.info(
                    f"No unprocessed documents found for connector {connector_id}. "
                    f"Processed {document_batch_counter} batches."
                )
                break

            document_batch_counter += 1
            last_lock_time = extend_lock(
                lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
            )
            logger.info(f"Processing document batch {document_batch_counter}")

            # Get the document attributes and entity types
            batch_metadata = _get_batch_documents_enhanced_metadata(
                unprocessed_document_batch,
                document_classification_extraction_instructions.get(
                    connector_source, {}
                ),
                connector_source,
            )

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

            # Iterate over batches of unprocessed documents
            # For each document:
            #   - extract implied entities and relationships
            #   - if deep extraction is enabled, extract entities and relationships with LLM
            #   - if deep extraction and classification are enabled, classify document
            #   - update postgres with
            #     - extracted entities (with classification) and relationships
            #     - kg_stage of the processed document

            documents_to_process = [x.id for x in unprocessed_document_batch]
            batch_implied_extraction: dict[str, KGImpliedExtractionResults] = {}
            batch_deep_extraction_args: list[
                tuple[str, KGEnhancedDocumentMetadata, KGImpliedExtractionResults]
            ] = []

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
                batch_implied_extraction[unprocessed_document.id] = (
                    kg_implied_extraction(
                        unprocessed_document,
                        batch_metadata[unprocessed_document.id],
                        active_entity_types,
                        kg_config_settings,
                    )
                )

                # 2. prepare inputs for deep extraction and classification
                if batch_metadata[unprocessed_document.id].deep_extraction:
                    batch_deep_extraction_args.append(
                        (
                            unprocessed_document.id,
                            batch_metadata[unprocessed_document.id],
                            batch_implied_extraction[unprocessed_document.id],
                        )
                    )

            # 2. perform deep extraction and classification in parallel
            batch_deep_extraction_func_calls = [
                (
                    kg_deep_extraction,
                    (
                        *arg,
                        tenant_id,
                        index_name,
                        kg_config_settings,
                    ),
                )
                for arg in batch_deep_extraction_args
            ]
            batch_deep_extractions: dict[str, KGDocumentDeepExtractionResults] = {
                document_id: result
                for document_id, result in zip(
                    documents_to_process,
                    run_functions_tuples_in_parallel(batch_deep_extraction_func_calls),
                )
            }

            # Collect entities and relationships to upsert
            batch_entities: list[tuple[str | None, str]] = []
            batch_relationships: list[tuple[str, str]] = []
            entity_classification: dict[str, str] = {}

            for document_id, implied_metadata in batch_implied_extraction.items():
                batch_entities += [
                    (None, entity) for entity in implied_metadata.implied_entities
                ]
                batch_entities.append((document_id, implied_metadata.document_entity))
                batch_relationships += [
                    (document_id, relationship)
                    for relationship in implied_metadata.implied_relationships
                ]

            for document_id, deep_extraction_result in batch_deep_extractions.items():
                batch_entities += [
                    (None, entity)
                    for entity in deep_extraction_result.deep_extracted_entities
                ]
                for relationship in deep_extraction_result.deep_extracted_relationships:
                    source_entity, _, target_entity = split_relationship_id(
                        relationship
                    )
                    if (
                        source_entity in active_entity_types
                        and target_entity in active_entity_types
                    ):
                        batch_relationships += [(document_id, relationship)]

                classification_result = deep_extraction_result.classification_result
                if not classification_result:
                    continue
                entity_classification[classification_result.document_entity] = (
                    classification_result.classification_class
                )

            # Populate the KG database with the extracted entities, relationships, and terms
            for potential_document_id, entity in batch_entities:
                # verify the entity is valid
                parts = split_entity_id(entity)
                if len(parts) != 2:
                    logger.error(
                        f"Invalid entity {entity} in aggregated_kg_extractions.entities"
                    )
                    continue

                entity_type, entity_name = parts
                entity_type = entity_type.upper()
                entity_name = entity_name.capitalize()

                if entity_type not in active_entity_types:
                    continue

                try:
                    with get_session_with_current_tenant() as db_session:
                        entity_attributes: dict[str, Any] = {}

                        if potential_document_id:
                            entity_attributes = (
                                batch_metadata[potential_document_id].document_metadata
                                or {}
                            )

                        # only keep selected attributes (and translate the attribute names)
                        metadata_attributes = entity_metadata_conversion_instructions[
                            entity_type
                        ]
                        keep_attributes = {
                            metadata_attributes[attr_name].name: attr_val
                            for attr_name, attr_val in entity_attributes.items()
                            if (
                                attr_name in metadata_attributes
                                and metadata_attributes[attr_name].keep
                            )
                        }

                        # add the classification result to the attributes
                        if entity in entity_classification:
                            keep_attributes["classification"] = entity_classification[
                                entity
                            ]

                        event_time = None
                        if potential_document_id:
                            event_time = get_document_updated_at(
                                potential_document_id, db_session
                            )

                        upserted_entity = upsert_staging_entity(
                            db_session=db_session,
                            name=entity_name,
                            entity_type=entity_type,
                            document_id=potential_document_id,
                            occurrences=1,
                            attributes=keep_attributes,
                            event_time=event_time,
                        )
                        metadata_tracker.track_metadata(
                            entity_type, upserted_entity.attributes
                        )

                        db_session.commit()
                except Exception as e:
                    logger.error(f"Error adding entity {entity}. Error message: {e}")

            for document_id, relationship in batch_relationships:
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
                    source_entity_type not in active_entity_types
                    or target_entity_type not in active_entity_types
                ):
                    continue

                relationship_type_id_name = extract_relationship_type_id(relationship)

                with get_session_with_current_tenant() as db_session:
                    try:
                        upsert_staging_relationship_type(
                            db_session=db_session,
                            source_entity_type=source_entity_type.upper(),
                            relationship_type=relationship_type,
                            target_entity_type=target_entity_type.upper(),
                            definition=False,
                            extraction_count=1,
                        )
                        db_session.commit()
                    except Exception as e:
                        logger.error(
                            f"Error adding relationship type {relationship_type_id_name} to the database: {e}"
                        )

                    with get_session_with_current_tenant() as db_session:
                        try:
                            upsert_staging_relationship(
                                db_session=db_session,
                                relationship_id_name=relationship,
                                source_document_id=document_id,
                                occurrences=1,
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

        # Update the the Skipped Docs back to Not Started
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
