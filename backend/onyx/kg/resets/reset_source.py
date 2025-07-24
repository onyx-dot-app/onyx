from redis.lock import Lock as RedisLock
from sqlalchemy import or_

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Connector
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.models import KGStage
from onyx.kg.resets.reset_index import reset_full_kg_index__commit
from onyx.kg.resets.reset_vespa import reset_vespa_kg_index


def reset_source_kg_index(
    source_name: str | None, tenant_id: str, index_name: str, lock: RedisLock
) -> None:
    """
    Resets the knowledge graph index and vespa for a source.
    """
    # reset vespa for the source
    reset_vespa_kg_index(tenant_id, index_name, lock, source_name)

    with get_session_with_current_tenant() as db_session:
        if source_name is None:
            reset_full_kg_index__commit(db_session)
            return

        # get all the entity types for the given source
        entity_types = [
            et.id_name
            for et in db_session.query(KGEntityType)
            .filter(KGEntityType.grounded_source_name == source_name)
            .all()
        ]
        if not entity_types:
            raise ValueError(f"There are no entity types for the source {source_name}")

        # delete the entity type from the knowledge graph
        for entity_type in entity_types:
            db_session.query(KGRelationship).filter(
                or_(
                    KGRelationship.source_node_type == entity_type,
                    KGRelationship.target_node_type == entity_type,
                )
            ).delete()
            db_session.query(KGRelationshipType).filter(
                or_(
                    KGRelationshipType.source_entity_type_id_name == entity_type,
                    KGRelationshipType.target_entity_type_id_name == entity_type,
                )
            ).delete()
            db_session.query(KGEntity).filter(
                KGEntity.entity_type_id_name == entity_type
            ).delete()
            db_session.query(KGRelationshipExtractionStaging).filter(
                or_(
                    KGRelationshipExtractionStaging.source_node_type == entity_type,
                    KGRelationshipExtractionStaging.target_node_type == entity_type,
                )
            ).delete()
            db_session.query(KGEntityExtractionStaging).filter(
                KGEntityExtractionStaging.entity_type_id_name == entity_type
            ).delete()
            db_session.query(KGRelationshipTypeExtractionStaging).filter(
                or_(
                    KGRelationshipTypeExtractionStaging.source_entity_type_id_name
                    == entity_type,
                    KGRelationshipTypeExtractionStaging.target_entity_type_id_name
                    == entity_type,
                )
            ).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        # get all the documents for the given source
        kg_connectors = [
            connector.id
            for connector in db_session.query(Connector)
            .filter(Connector.source == DocumentSource(source_name))
            .all()
        ]
        document_ids = [
            cc_pair.id
            for cc_pair in db_session.query(DocumentByConnectorCredentialPair)
            .filter(DocumentByConnectorCredentialPair.connector_id.in_(kg_connectors))
            .all()
        ]

        # reset the kg stage for the documents
        db_session.query(Document).filter(Document.id.in_(document_ids)).update(
            {"kg_stage": KGStage.NOT_STARTED}
        )
        db_session.commit()
