from typing import cast
from typing import Set

from rapidfuzz.fuzz import ratio
from sqlalchemy import text

from onyx.configs.kg_configs import KG_CLUSTERING_RETRIVE_THRESHOLD
from onyx.configs.kg_configs import KG_CLUSTERING_THRESHOLD
from onyx.db.document import update_document_kg_info
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import delete_entities_by_id_names
from onyx.db.entities import get_entities_by_grounding
from onyx.db.entities import KGEntity
from onyx.db.entities import KGEntityExtractionStaging
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.db.relationships import delete_relationship_types_by_id_names
from onyx.db.relationships import delete_relationships_by_id_names
from onyx.db.relationships import get_all_relationship_types
from onyx.db.relationships import get_all_relationships
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage
from onyx.utils.logger import setup_logger

# from sklearn.cluster import SpectralClustering  # type: ignore

logger = setup_logger()


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

    source_documents_w_successful_transfers: set[str] = set()
    source_documents_w_failed_transfers: set[str] = set()

    with get_session_with_current_tenant() as db_session:

        relationship_types = get_all_relationship_types(
            db_session, kg_stage=KGStage.EXTRACTED
        )

        relationships = get_all_relationships(db_session, kg_stage=KGStage.EXTRACTED)

        grounded_entities: list[KGEntityExtractionStaging] = cast(
            list[KGEntityExtractionStaging],
            get_entities_by_grounding(
                db_session, KGStage.EXTRACTED, KGGroundingType.GROUNDED
            ),
        )

    ## Clustering

    # TODO: re-implement clustering of ungrounded entities as well as
    # grounded entities that do not have a source document with deep extraction enabled!
    # For now we would just dedupe grounded entities that have very similar names
    # This will be reimplemented when deep extraction is enabled.

    transferred_entities: list[str] = []
    cluster_translations: dict[str, str] = {}

    # transfer the initial grounded entities
    unclustered_grounded_entities: list[KGEntityExtractionStaging] = []
    for entity in grounded_entities:
        # save entities without a document_id to cluster later
        if entity.document_id is None:
            unclustered_grounded_entities.append(entity)
            continue

        # add the entities with a document_id
        with get_session_with_current_tenant() as db_session:
            added_entity = add_entity(
                db_session,
                KGStage.NORMALIZED,
                entity_type=entity.entity_type_id_name,
                name=entity.name,
                document_id=entity.document_id,
                occurrences=entity.occurrences or 1,
                attributes=entity.attributes,
                alternative_names=entity.alternative_names or [],
            )
            if added_entity:
                transferred_entities.append(added_entity.id_name)
            db_session.commit()

    # cluster the entities without a document_id
    remaining_grounded_entities: list[KGEntityExtractionStaging] = []
    for entity in unclustered_grounded_entities:
        # find potential cluster candidates, uses GIN index, very efficient
        with get_session_with_current_tenant() as db_session:
            db_session.execute(
                text(
                    f"SET pg_trgm.similarity_threshold = {KG_CLUSTERING_RETRIVE_THRESHOLD}"
                )
            )
            similar_entities = (
                db_session.query(KGEntityExtractionStaging)
                .filter(
                    # find from clustered_grounded_entities
                    # entities of the same entity type with a similar name
                    KGEntityExtractionStaging.document_id.is_not(None),
                    KGEntityExtractionStaging.entity_type_id_name
                    == entity.entity_type_id_name,
                    KGEntityExtractionStaging.clustering_name.op("%")(
                        entity.clustering_name
                    ),
                )
                .all()
            )

        # assign them to the nearest cluster if we're confident they're the same entity
        best_score = -1.0
        best_entity = None
        for similar in similar_entities:
            # skip those with numbers so we don't cluster version1 and version2, etc.
            if any(char.isdigit() for char in similar.clustering_name):
                continue
            score = ratio(similar.clustering_name, entity.clustering_name)
            if score >= KG_CLUSTERING_THRESHOLD and score > best_score:
                best_score = score
                best_entity = similar

        if best_entity:
            # update the cluster entity's occurence and alternative names
            with get_session_with_current_tenant() as db_session:
                occurence = (best_entity.occurrences or 1) + (entity.occurrences or 1)
                alternative_names = set(best_entity.alternative_names)
                alternative_names.add(entity.name)

                transferred_entities.append(entity.id_name)
                cluster_translations[entity.id_name] = best_entity.id_name

                logger.debug(f"Clustered {entity.id_name} into {best_entity.id_name}")
                db_session.query(KGEntity).filter(
                    KGEntity.id_name == best_entity.id_name
                ).update(
                    {
                        "occurrences": occurence,
                        "alternative_names": list(alternative_names),
                    }
                )
                db_session.commit()
        else:
            remaining_grounded_entities.append(entity)

    # transfer over the remaining unclustered entities
    for entity in remaining_grounded_entities:
        with get_session_with_current_tenant() as db_session:
            added_entity = add_entity(
                db_session,
                KGStage.NORMALIZED,
                entity_type=entity.entity_type_id_name,
                name=entity.name,
                document_id=None,
                occurrences=entity.occurrences or 1,
                attributes=entity.attributes,
                alternative_names=entity.alternative_names or [],
            )
            if added_entity:
                transferred_entities.append(added_entity.id_name)
            db_session.commit()

    ## Database operations

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

    transferred_relationships: list[str] = []
    for relationship in relationships:
        with get_session_with_current_tenant() as db_session:
            try:
                # update the id_name
                (
                    source_entity_id_name,
                    relationship_string,
                    target_entity_id_name,
                ) = relationship.id_name.split("__")

                new_relationship_id_name = "__".join(
                    (
                        cluster_translations.get(
                            source_entity_id_name, source_entity_id_name
                        ),
                        relationship_string,
                        cluster_translations.get(
                            target_entity_id_name, target_entity_id_name
                        ),
                    )
                )
                add_relationship(
                    db_session,
                    KGStage.NORMALIZED,
                    relationship_id_name=new_relationship_id_name,
                    source_document_id=relationship.source_document or "",
                    occurrences=relationship.occurrences or 1,
                )

                if relationship.source_document:
                    source_documents_w_successful_transfers.add(
                        relationship.source_document
                    )

                db_session.commit()

                transferred_relationships.append(relationship.id_name)

            except Exception as e:
                if relationship.source_document:
                    source_documents_w_failed_transfers.add(
                        relationship.source_document
                    )
                logger.error(
                    f"Error transferring relationship {relationship.id_name}: {e}"
                )

    # TODO: remove the /relationship types & entities that correspond to relationships
    # source documents that failed to transfer. I.e, do a proper rollback

    # TODO: update Vespa info when clustering/changes are performed

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

    # Update document kg info

    # with get_session_with_current_tenant() as db_session:
    #     all_kg_extracted_documents_info = get_all_kg_extracted_documents_info(
    #         db_session
    #     )

    for document_id in source_documents_w_successful_transfers:

        # Update the document kg info
        with get_session_with_current_tenant() as db_session:
            update_document_kg_info(
                db_session,
                document_id=document_id,
                kg_stage=KGStage.NORMALIZED,
            )
            db_session.commit()
