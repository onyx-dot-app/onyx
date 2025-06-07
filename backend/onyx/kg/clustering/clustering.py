from typing import cast

from rapidfuzz.fuzz import ratio
from sqlalchemy import func
from sqlalchemy import text

from onyx.configs.kg_configs import KG_CLUSTERING_RETRIEVE_THRESHOLD
from onyx.configs.kg_configs import KG_CLUSTERING_THRESHOLD
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import KGEntity
from onyx.db.entities import KGEntityExtractionStaging
from onyx.db.entities import merge_entities
from onyx.db.entities import transfer_entity
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.relationships import get_parent_child_relationships_and_types
from onyx.db.relationships import transfer_relationship
from onyx.db.relationships import transfer_relationship_type
from onyx.document_index.vespa.kg_interactions import (
    get_kg_vespa_info_update_requests_for_document,
)
from onyx.document_index.vespa.kg_interactions import update_kg_chunks_vespa_info
from onyx.kg.models import KGGroundingType
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

logger = setup_logger()


def _cluster_one_grounded_entity(
    entity: KGEntityExtractionStaging,
) -> tuple[KGEntity, bool]:
    """
    Cluster a single grounded entity.
    """
    with get_session_with_current_tenant() as db_session:
        # get entity name and filtering conditions
        if entity.document_id is not None:
            entity_name = cast(
                str,
                db_session.query(Document.semantic_id)
                .filter(Document.id == entity.document_id)
                .scalar(),
            ).lower()
            filtering = [KGEntity.document_id.is_(None)]
        else:
            entity_name = entity.name.lower()
            filtering = []

        # skip those with numbers so we don't cluster version1 and version2, etc.
        similar_entities: list[KGEntity] = []
        if not any(char.isdigit() for char in entity_name):
            # find similar entities, uses GIN index, very efficient
            db_session.execute(
                text(
                    "SET pg_trgm.similarity_threshold = "
                    + str(KG_CLUSTERING_RETRIEVE_THRESHOLD)
                )
            )
            similar_entities = (
                db_session.query(KGEntity)
                .filter(
                    # find entities of the same type with a similar name
                    *filtering,
                    KGEntity.entity_type_id_name == entity.entity_type_id_name,
                    getattr(func, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE).similarity_op(
                        KGEntity.name, entity_name
                    ),
                )
                .all()
            )

    # find best match
    best_score = -1.0
    best_entity = None
    for similar in similar_entities:
        # skip those with numbers so we don't cluster version1 and version2, etc.
        if any(char.isdigit() for char in similar.name):
            continue
        score = ratio(similar.name, entity_name)
        if score >= KG_CLUSTERING_THRESHOLD * 100 and score > best_score:
            best_score = score
            best_entity = similar

    # if there is a match, update the entity, otherwise create a new one
    with get_session_with_current_tenant() as db_session:
        if best_entity:
            logger.debug(f"Merged {entity.name} with {best_entity.name}")
            update_vespa = (
                best_entity.document_id is None and entity.document_id is not None
            )
            transferred_entity = merge_entities(
                db_session=db_session, parent=best_entity, child=entity
            )
        else:
            update_vespa = entity.document_id is not None
            transferred_entity = transfer_entity(db_session=db_session, entity=entity)

        db_session.commit()

    return transferred_entity, update_vespa


def _transfer_batch_relationship(
    relationships: list[KGRelationshipExtractionStaging],
    entity_translations: dict[str, str],
) -> set[str]:
    updated_documents: set[str] = set()

    with get_session_with_current_tenant() as db_session:
        entity_id_names: set[str] = set()
        for relationship in relationships:
            transferred_relationship = transfer_relationship(
                db_session=db_session,
                relationship=relationship,
                entity_translations=entity_translations,
            )
            entity_id_names.add(transferred_relationship.source_node)
            entity_id_names.add(transferred_relationship.target_node)

        updated_documents.update(
            (
                res[0]
                for res in db_session.query(KGEntity.document_id)
                .filter(KGEntity.id_name.in_(entity_id_names))
                .all()
                if res[0] is not None
            )
        )
        db_session.commit()

    return updated_documents


def kg_clustering(
    tenant_id: str, index_name: str, processing_chunk_batch_size: int = 16
) -> None:
    """
    Here we will cluster the extractions based on their cluster frameworks.
    Initially, this will only focus on grounded entities with pre-determined
    relationships, so 'clustering' is actually not yet required.
    However, we may need to reconcile entities coming from different sources.

    The primary purpose of this function is to populate the actual KG tables
    from the temp_extraction tables.

    This will change with deep extraction, where grounded-sourceless entities
    can be extracted and then need to be clustered.
    """

    # TODO: revisit splitting into batches

    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    with get_session_with_current_tenant() as db_session:
        kg_config_settings = get_kg_config_settings(db_session)

    # Retrieve staging data
    with get_session_with_current_tenant() as db_session:
        untransferred_relationship_types = (
            db_session.query(KGRelationshipTypeExtractionStaging)
            .filter(KGRelationshipTypeExtractionStaging.transferred.is_(False))
            .all()
        )
        untransferred_relationships = (
            db_session.query(KGRelationshipExtractionStaging)
            .filter(KGRelationshipExtractionStaging.transferred.is_(False))
            .all()
        )
        grounded_entities = (
            db_session.query(KGEntityExtractionStaging)
            .join(
                KGEntityType,
                KGEntityExtractionStaging.entity_type_id_name == KGEntityType.id_name,
            )
            .filter(KGEntityType.grounding == KGGroundingType.GROUNDED)
            .all()
        )

    # Cluster and transfer grounded entities
    untransferred_grounded_entities = [
        entity for entity in grounded_entities if entity.transferred_id_name is None
    ]
    entity_translations: dict[str, str] = {
        entity.id_name: entity.transferred_id_name
        for entity in grounded_entities
        if entity.transferred_id_name is not None
    }
    vespa_update_documents: set[str] = set()

    for entity in untransferred_grounded_entities:
        added_entity, update_vespa = _cluster_one_grounded_entity(entity)
        entity_translations[entity.id_name] = added_entity.id_name
        if update_vespa and added_entity.document_id is not None:
            vespa_update_documents.add(added_entity.document_id)
    logger.info(f"Transferred {len(untransferred_grounded_entities)} entities")

    # Add parent-child relationships and relationship types
    with get_session_with_current_tenant() as db_session:
        parent_child_relationships, parent_child_relationship_types = (
            get_parent_child_relationships_and_types(
                db_session, depth=kg_config_settings.KG_MAX_PARENT_RECURSION_DEPTH
            )
        )
        untransferred_relationship_types.extend(parent_child_relationship_types)
        untransferred_relationships.extend(parent_child_relationships)
        db_session.commit()

    # Transfer the relationship types
    for relationship_type in untransferred_relationship_types:
        with get_session_with_current_tenant() as db_session:
            transfer_relationship_type(db_session, relationship_type=relationship_type)
            db_session.commit()
    logger.info(
        f"Transferred {len(untransferred_relationship_types)} relationship types"
    )

    # Transfer relationships in parallel
    updated_documents_batch: list[set[str]] = run_functions_tuples_in_parallel(
        [
            (
                _transfer_batch_relationship,
                (
                    untransferred_relationships[
                        batch_i : batch_i + processing_chunk_batch_size
                    ],
                    entity_translations,
                ),
            )
            for batch_i in range(
                0, len(untransferred_relationships), processing_chunk_batch_size
            )
        ]
    )
    for updated_documents in updated_documents_batch:
        vespa_update_documents.update(updated_documents)
    logger.info(f"Transferred {len(untransferred_relationships)} relationships")

    # Update vespa for documents that had their kg info updated in parallel
    for i in range(0, len(vespa_update_documents), processing_chunk_batch_size):
        batch_update_requests = run_functions_tuples_in_parallel(
            [
                (
                    get_kg_vespa_info_update_requests_for_document,
                    (document_id, index_name, tenant_id),
                )
                for document_id in list(vespa_update_documents)[
                    i : i + processing_chunk_batch_size
                ]
            ]
        )
        for update_requests in batch_update_requests:
            update_kg_chunks_vespa_info(update_requests, index_name, tenant_id)

    # Delete the transferred objects from the staging tables
    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGRelationshipExtractionStaging).filter(
                KGRelationshipExtractionStaging.transferred.is_(True)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationships: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGRelationshipTypeExtractionStaging).filter(
                KGRelationshipTypeExtractionStaging.transferred.is_(True)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationship types: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGEntityExtractionStaging).filter(
                KGEntityExtractionStaging.transferred_id_name.is_not(None)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting entities: {e}")
