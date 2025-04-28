from typing import Set

from onyx.db.document import update_document_kg_info
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import delete_entities_by_id_names
from onyx.db.entities import get_entities_by_grounding
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.db.relationships import delete_relationship_types_by_id_names
from onyx.db.relationships import delete_relationships_by_id_names
from onyx.db.relationships import get_all_relationship_types
from onyx.db.relationships import get_all_relationships
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_clustering(
    tenant_id: str, index_name: str, processing_chunk_batch_size: int = 8
) -> None:
    """
    Here we will cluster the extractions based on their cluster frameworks.
    Initially, this will only focus on grounded entities with pre-determined
    relationships, so clustering is actually not yet required.
    The primary purpose of this function is to populate the actual KG tables
    from the temp_extraction tables.

    This will change with deep extraction, where grounded-sourceless entities
    can be extracted and then need to be clustered.
    """

    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    ## Retrieval

    source_documents_w_successful_transfers: Set[str] = set()
    source_documents_w_failed_transfers: Set[str] = set()

    # get onjects that are now in the Staging tables

    with get_session_with_current_tenant() as db_session:

        relationship_types = get_all_relationship_types(
            db_session, kg_stage=KGStage.EXTRACTED
        )

        relationships = get_all_relationships(db_session, kg_stage=KGStage.EXTRACTED)

        grounded_entities = get_entities_by_grounding(
            db_session, KGStage.EXTRACTED, KGGroundingType.GROUNDED
        )

    ## Clustering

    # TODO: we will re-implement the cluster matching logic here

    ## Database operations

    # create the clustered objects - entities

    transferred_entities: list[str] = []
    for grounded_entity in grounded_entities:
        with get_session_with_current_tenant() as db_session:
            added_entity = add_entity(
                db_session,
                KGStage.NORMALIZED,
                entity_type=grounded_entity.entity_type_id_name,
                name=grounded_entity.name,
                occurances=grounded_entity.occurances or 1,
                document_id=grounded_entity.document_id or None,
                attributes=grounded_entity.attributes or None,
            )

            db_session.commit()

            transferred_entities.append(added_entity.id_name)

    transferred_relationship_types: list[str] = []
    for relationship_type in relationship_types:
        with get_session_with_current_tenant() as db_session:
            added_relationship_type = add_relationship_type(
                KGStage.NORMALIZED,
                source_entity_type=relationship_type.source_entity_type,
                relationship_type=relationship_type.relationship_type,
                target_entity_type=relationship_type.target_entity_type,
                extraction_count=relationship_type.extraction_count,
            )

            db_session.commit()

            transferred_relationship_types.append(added_relationship_type.id_name)

    transferred_relationships: list[str] = []
    for relationship in relationships:
        with get_session_with_current_tenant() as db_session:
            try:
                added_relationship = add_relationship(
                    KGStage.NORMALIZED,
                    source_entity_type=relationship.source_entity_type,
                    relationship_type=relationship.relationship_type,
                    target_entity_type=relationship.target_entity_type,
                    extraction_count=relationship.extraction_count,
                )

                source_documents_w_successful_transfers.add(
                    relationship.source_document
                )

                db_session.commit()

                transferred_relationships.append(added_relationship.id_name)

            except Exception as e:
                source_documents_w_failed_transfers.add(relationship.source_document)
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
