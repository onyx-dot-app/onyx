from sqlalchemy import or_

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.models import KGStage


def reset_entity_type_kg_index(entity_type_id_name: str) -> None:
    """
    Resets the knowledge graph index for a connector.
    """

    with get_session_with_current_tenant() as db_session:
        # check the entity type exists
        entity_type = (
            db_session.query(KGEntityType)
            .filter(KGEntityType.id_name == entity_type_id_name)
            .first()
        )
        if not entity_type:
            raise ValueError(f"Entity type with id {entity_type_id_name} not found")

        # get entity documents
        document_ids = {
            entity.document_id
            for entity in db_session.query(KGEntity)
            .filter(KGEntity.entity_type_id_name == entity_type_id_name)
            .all()
        }

        # delete the entity type from the knowledge graph
        db_session.query(KGRelationship).filter(
            or_(
                KGRelationship.source_node_type == entity_type_id_name,
                KGRelationship.target_node_type == entity_type_id_name,
            )
        ).delete()
        db_session.query(KGRelationshipType).filter(
            or_(
                KGRelationshipType.source_entity_type_id_name == entity_type_id_name,
                KGRelationshipType.target_entity_type_id_name == entity_type_id_name,
            )
        ).delete()
        db_session.query(KGEntity).filter(
            KGEntity.entity_type_id_name == entity_type_id_name
        ).delete()
        db_session.query(KGRelationshipExtractionStaging).filter(
            or_(
                KGRelationshipExtractionStaging.source_node_type == entity_type_id_name,
                KGRelationshipExtractionStaging.target_node_type == entity_type_id_name,
            )
        ).delete()
        db_session.query(KGEntityExtractionStaging).filter(
            KGEntityExtractionStaging.entity_type_id_name == entity_type_id_name
        ).delete()
        db_session.query(KGRelationshipTypeExtractionStaging).filter(
            or_(
                KGRelationshipTypeExtractionStaging.source_entity_type_id_name
                == entity_type_id_name,
                KGRelationshipTypeExtractionStaging.target_entity_type_id_name
                == entity_type_id_name,
            )
        ).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        db_session.query(Document).filter(Document.id.in_(document_ids)).update(
            {"kg_stage": KGStage.NOT_STARTED}
        )
        db_session.commit()


def reset_entity_type_extraction_kg_index(del_entity_type: str) -> None:
    """
    Resets the knowledge graph entity type extraction index.
    """
    with get_session_with_current_tenant() as db_session:
        # Update kg_stage for affected documents using a join
        db_session.query(Document).join(
            KGEntityExtractionStaging,
            Document.id == KGEntityExtractionStaging.document_id,
        ).filter(
            KGEntityExtractionStaging.entity_type_id_name == del_entity_type
        ).update(
            {Document.kg_stage: KGStage.NOT_STARTED}
        )

        db_session.query(KGRelationshipExtractionStaging).filter(
            (KGRelationshipExtractionStaging.source_node_type == del_entity_type)
            | (KGRelationshipExtractionStaging.target_node_type == del_entity_type)
        ).delete()
        db_session.query(KGEntityExtractionStaging).filter(
            KGEntityExtractionStaging.entity_type_id_name == del_entity_type
        ).delete()
        db_session.query(KGRelationshipTypeExtractionStaging).filter(
            (
                KGRelationshipTypeExtractionStaging.source_entity_type_id_name
                == del_entity_type
            )
            | (
                KGRelationshipTypeExtractionStaging.target_entity_type_id_name
                == del_entity_type
            )
        ).delete()
        db_session.commit()
