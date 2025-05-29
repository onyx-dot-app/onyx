from typing import cast

from rapidfuzz.fuzz import ratio
from sqlalchemy import text

from onyx.configs.kg_configs import KG_CLUSTERING_RETRIEVE_THRESHOLD
from onyx.configs.kg_configs import KG_CLUSTERING_THRESHOLD
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import delete_entities_by_id_names
from onyx.db.entities import KGEntity
from onyx.db.entities import KGEntityExtractionStaging
from onyx.db.entities import merge_entities
from onyx.db.entities import transfer_entity
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.relationships import add_relationship_type
from onyx.db.relationships import delete_relationship_types_by_id_names
from onyx.db.relationships import delete_relationships_by_id_names
from onyx.db.relationships import get_all_relationship_types
from onyx.db.relationships import transfer_relationship
from onyx.document_index.vespa.kg_interactions import (
    update_kg_chunks_vespa_info_for_entity,
)
from onyx.document_index.vespa.kg_interactions import (
    update_kg_chunks_vespa_info_for_relationship,
)
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def _cluster_one_grounded_entity(
    entity: KGEntityExtractionStaging, tenant_id: str, index_name: str
) -> KGEntity:
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
                    KGEntity.name.op("%")(entity_name),
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

    # update vespa
    if update_vespa:
        update_kg_chunks_vespa_info_for_entity(
            entity=transferred_entity, index_name=index_name, tenant_id=tenant_id
        )

    return transferred_entity


def _transfer_batch_relationship(
    relationships: list[KGRelationshipExtractionStaging],
    entity_translations: dict[str, str],
    index_name: str,
    tenant_id: str,
) -> list[str]:
    transferred_relationships: list[str] = []
    added_relationships: list[KGRelationship] = []

    with get_session_with_current_tenant() as db_session:
        for relationship in relationships:
            added_relationship = transfer_relationship(
                db_session=db_session,
                relationship=relationship,
                entity_translations=entity_translations,
            )
            transferred_relationships.append(relationship.id_name)
            added_relationships.append(added_relationship)
        db_session.commit()

    # update vespa
    for added_relationship in added_relationships:
        update_kg_chunks_vespa_info_for_relationship(
            relationship=added_relationship,
            index_name=index_name,
            tenant_id=tenant_id,
        )
    return transferred_relationships


def kg_clustering(
    tenant_id: str, index_name: str, processing_chunk_batch_size: int = 8
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

    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    ## Retrieval
    with get_session_with_current_tenant() as db_session:
        relationship_types = get_all_relationship_types(
            db_session, kg_stage=KGStage.EXTRACTED
        )

        relationships = db_session.query(KGRelationshipExtractionStaging).all()
        grounded_entities = (
            db_session.query(KGEntityExtractionStaging)
            .join(
                KGEntityType,
                KGEntityExtractionStaging.entity_type_id_name == KGEntityType.id_name,
            )
            .filter(KGEntityType.grounding == KGGroundingType.GROUNDED)
            .all()
        )

    ## Clustering

    # TODO: implement clustering of ungrounded entities
    # For now we would just dedupe grounded entities that have very similar names
    # This will be reimplemented when deep extraction is enabled.

    transferred_entities: list[str] = []
    entity_translations: dict[str, str] = {}

    for entity in grounded_entities:
        added_entity = _cluster_one_grounded_entity(entity, tenant_id, index_name)
        transferred_entities.append(entity.id_name)
        entity_translations[entity.id_name] = added_entity.id_name
    logger.info(f"Transferred {len(transferred_entities)} entities")

    ## Transfer the relationship types
    transferred_relationship_types: list[str] = []
    for relationship_type in relationship_types:
        with get_session_with_current_tenant() as db_session:
            added_relationship_type_id_name = add_relationship_type(
                db_session,
                KGStage.NORMALIZED,
                source_entity_type=relationship_type.source_entity_type_id_name,
                relationship_type=relationship_type.type,
                target_entity_type=relationship_type.target_entity_type_id_name,
                extraction_count=relationship_type.occurrences or 1,
            )
            db_session.commit()
            transferred_relationship_types.append(added_relationship_type_id_name)
    logger.info(f"Transferred {len(transferred_relationship_types)} relationship types")

    ## Transfer the relationships in parallel
    tasks = [
        (
            _transfer_batch_relationship,
            (
                relationships[batch_i : batch_i + processing_chunk_batch_size],
                entity_translations,
                index_name,
                tenant_id,
            ),
        )
        for batch_i in range(0, len(relationships), processing_chunk_batch_size)
    ]
    results = run_functions_tuples_in_parallel(tasks)
    transferred_relationships = []
    for result in results:
        transferred_relationships.extend(result)
    logger.info(f"Transferred {len(transferred_relationships)} relationships")

    # delete the added objects from the staging tables
    try:
        with get_session_with_current_tenant() as db_session:
            delete_relationships_by_id_names(
                db_session, transferred_relationships, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationships: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            delete_relationship_types_by_id_names(
                db_session, transferred_relationship_types, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationship types: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            delete_entities_by_id_names(
                db_session, transferred_entities, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting entities: {e}")
