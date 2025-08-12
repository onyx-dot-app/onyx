import uuid
from datetime import datetime
from datetime import timezone
from typing import List

from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

import onyx.db.document as dbdocument
from onyx.db.entity_type import UNGROUNDED_SOURCE_NAME
from onyx.db.models import Document
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGEntityType
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage
from onyx.kg.utils.formatting_utils import make_entity_id


def upsert_staging_entity(
    db_session: Session,
    name: str,
    entity_type: str,
    document_id: str | None = None,
    occurrences: int = 1,
    attributes: dict[str, str] | None = None,
    event_time: datetime | None = None,
) -> KGEntityExtractionStaging:
    """Add or update a new staging entity to the database.

    Args:
        db_session: SQLAlchemy session
        name: Name of the entity
        entity_type: Type of the entity (must match an existing KGEntityType)
        document_id: ID of the document the entity belongs to
        occurrences: Number of times this entity has been found
        attributes: Attributes of the entity
        event_time: Time the entity was added to the database

    Returns:
        KGEntityExtractionStaging: The created entity
    """
    entity_type = entity_type.upper()
    name = name.title()
    id_name = make_entity_id(entity_type, name)
    attributes = attributes or {}

    entity_key = attributes.get("key")
    entity_parent = attributes.get("parent")

    keep_attributes = {
        attr_key: attr_val
        for attr_key, attr_val in attributes.items()
        if attr_key not in ("key", "parent")
    }

    # Create new entity
    stmt = (
        pg_insert(KGEntityExtractionStaging)
        .values(
            id_name=id_name,
            name=name,
            entity_type_id_name=entity_type,
            entity_key=entity_key,
            parent_key=entity_parent,
            document_id=document_id,
            occurrences=occurrences,
            attributes=keep_attributes,
            event_time=event_time,
        )
        .on_conflict_do_update(
            index_elements=["id_name"],
            set_=dict(
                occurrences=KGEntityExtractionStaging.occurrences + occurrences,
            ),
        )
        .returning(KGEntityExtractionStaging)
    )

    result = db_session.execute(stmt).scalar()
    if result is None:
        raise RuntimeError(
            f"Failed to create or increment staging entity with id_name: {id_name}"
        )

    # Update the document's kg_stage if document_id is provided
    if document_id is not None:
        db_session.query(Document).filter(Document.id == document_id).update(
            {
                "kg_stage": KGStage.EXTRACTED,
                "kg_processing_time": datetime.now(timezone.utc),
            }
        )
    db_session.flush()

    return result


def transfer_entity(
    db_session: Session,
    entity: KGEntityExtractionStaging,
) -> KGEntity:
    """Transfer an entity from the extraction staging table to the normalized table.

    Args:
        db_session: SQLAlchemy session
        entity: Entity to transfer

    Returns:
        KGEntity: The transferred entity
    """
    # Create the transferred entity
    stmt = (
        pg_insert(KGEntity)
        .values(
            id_name=make_entity_id(entity.entity_type_id_name, uuid.uuid4().hex[:20]),
            name=entity.name.casefold(),
            entity_key=entity.entity_key,
            parent_key=entity.parent_key,
            alternative_names=entity.alternative_names or [],
            entity_type_id_name=entity.entity_type_id_name,
            document_id=entity.document_id,
            occurrences=entity.occurrences,
            attributes=entity.attributes,
            event_time=entity.event_time,
        )
        .on_conflict_do_update(
            index_elements=["name", "entity_type_id_name", "document_id"],
            set_=dict(
                occurrences=KGEntity.occurrences + entity.occurrences,
                attributes=KGEntity.attributes.op("||")(
                    literal(entity.attributes, JSONB)
                ),
                entity_key=func.coalesce(KGEntity.entity_key, entity.entity_key),
                parent_key=func.coalesce(KGEntity.parent_key, entity.parent_key),
                event_time=entity.event_time,
                time_updated=datetime.now(),
            ),
        )
        .returning(KGEntity)
    )
    new_entity = db_session.execute(stmt).scalar()
    if new_entity is None:
        raise RuntimeError(f"Failed to transfer entity with id_name: {entity.id_name}")

    # Update the document's kg_stage if document_id is provided
    if entity.document_id is not None:
        dbdocument.update_document_kg_info(
            db_session,
            document_id=entity.document_id,
            kg_stage=KGStage.NORMALIZED,
        )

    # Update transferred
    db_session.query(KGEntityExtractionStaging).filter(
        KGEntityExtractionStaging.id_name == entity.id_name
    ).update({"transferred_id_name": new_entity.id_name})
    db_session.flush()

    return new_entity


def merge_entities(
    db_session: Session, parent: KGEntity, child: KGEntityExtractionStaging
) -> KGEntity:
    """Merge an entity from the extraction staging table into
    an existing entity in the normalized table.

    Args:
        db_session: SQLAlchemy session
        parent: Parent entity to merge into
        child: Child staging entity to merge

    Returns:
        KGEntity: The merged entity
    """
    # check we're not merging two entities with different document_ids
    if (
        parent.document_id is not None
        and child.document_id is not None
        and parent.document_id != child.document_id
    ):
        raise ValueError(
            "Overwriting the document_id of an entity with a document_id already is not allowed"
        )

    # update the parent entity (only document_id, alternative_names, occurrences)
    setting_doc = parent.document_id is None and child.document_id is not None
    document_id = child.document_id if setting_doc else parent.document_id
    alternative_names = set(parent.alternative_names or [])
    alternative_names.update(child.alternative_names or [])
    alternative_names.add(child.name.lower())
    alternative_names.discard(parent.name)

    stmt = (
        update(KGEntity)
        .where(KGEntity.id_name == parent.id_name)
        .values(
            document_id=document_id,
            alternative_names=list(alternative_names),
            occurrences=parent.occurrences + child.occurrences,
            attributes=parent.attributes | child.attributes,
            entity_key=parent.entity_key or child.entity_key,
            parent_key=parent.parent_key or child.parent_key,
        )
        .returning(KGEntity)
    )

    result = db_session.execute(stmt).scalar()
    if result is None:
        raise RuntimeError(f"Failed to merge entities with id_name: {parent.id_name}")

    # Update the document's kg_stage if document_id is set
    if setting_doc and child.document_id is not None:
        dbdocument.update_document_kg_info(
            db_session,
            document_id=child.document_id,
            kg_stage=KGStage.NORMALIZED,
        )

    # Update transferred
    db_session.query(KGEntityExtractionStaging).filter(
        KGEntityExtractionStaging.id_name == child.id_name
    ).update({"transferred_id_name": parent.id_name})
    db_session.flush()

    return result


def get_kg_entity_by_document(db: Session, document_id: str) -> KGEntity | None:
    """
    Check if a document_id exists in the kg_entities table and return its id_name if found.

    Args:
        db: SQLAlchemy database session
        document_id: The document ID to search for

    Returns:
        The id_name of the matching KGEntity if found, None otherwise
    """
    query = select(KGEntity).where(KGEntity.document_id == document_id)
    result = db.execute(query).scalar()
    return result


def get_grounded_entities_by_types(
    db_session: Session, entity_types: List[str], grounding: KGGroundingType
) -> List[KGEntity]:
    """Get all entities matching an entity_type.

    Args:
        db_session: SQLAlchemy session
        entity_types: List of entity types to filter by

    Returns:
        List of KGEntity objects belonging to the specified entity types
    """
    return (
        db_session.query(KGEntity)
        .join(KGEntityType, KGEntity.entity_type_id_name == KGEntityType.id_name)
        .filter(KGEntity.entity_type_id_name.in_(entity_types))
        .filter(KGEntityType.grounding == grounding)
        .all()
    )


def get_document_id_for_entity(db_session: Session, entity_id_name: str) -> str | None:
    """Get the document ID associated with an entity.

    Args:
        db_session: SQLAlchemy database session
        entity_id_name: The entity id_name to look up

    Returns:
        The document ID if found, None otherwise
    """
    entity = (
        db_session.query(KGEntity).filter(KGEntity.id_name == entity_id_name).first()
    )
    return entity.document_id if entity else None


def delete_from_kg_entities_extraction_staging__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete entities from the extraction staging table."""
    db_session.query(KGEntityExtractionStaging).filter(
        KGEntityExtractionStaging.document_id.in_(document_ids)
    ).delete(synchronize_session=False)


def delete_from_kg_entities__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete entities from the normalized table."""
    db_session.query(KGEntity).filter(KGEntity.document_id.in_(document_ids)).delete(
        synchronize_session=False
    )


def get_entity_name(db_session: Session, entity_id_name: str) -> str | None:
    """Get the name of an entity."""
    entity = (
        db_session.query(KGEntity).filter(KGEntity.id_name == entity_id_name).first()
    )
    return entity.name if entity else None


def get_entity_stats_by_grounded_source_name(
    db_session: Session,
) -> dict[str, tuple[datetime, int]]:
    """
    Returns a dict mapping each grounded_source_name to a tuple in which:
        - the first element is the latest update time across all entities with the same entity-type
        - the second element is the count of `KGEntity`s
    """
    results = (
        db_session.query(
            KGEntityType.grounded_source_name,
            func.count(KGEntity.id_name).label("entities_count"),
            func.max(KGEntity.time_updated).label("last_updated"),
        )
        .join(KGEntityType, KGEntity.entity_type_id_name == KGEntityType.id_name)
        .group_by(KGEntityType.grounded_source_name)
        .all()
    )

    # `row.grounded_source_name` is NULLABLE in the database schema.
    # Thus, for all "ungrounded" entity-types, we use a default name.
    return {
        (row.grounded_source_name or UNGROUNDED_SOURCE_NAME): (
            row.last_updated,
            row.entities_count,
        )
        for row in results
    }
