from datetime import datetime
from typing import cast
from typing import List
from typing import Type

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import Document
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGEntityType
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage


def add_entity(
    db_session: Session,
    kg_stage: KGStage,
    entity_type: str,
    name: str,
    document_id: str | None = None,
    occurrences: int = 0,
    event_time: datetime | None = None,
    attributes: dict[str, str] | None = None,
) -> "KGEntity | KGEntityExtractionStaging | None":
    """Add a new entity to the database.

    Args:
        db_session: SQLAlchemy session
        kg_stage: KGStage of the entity
        entity_type: Type of the entity (must match an existing KGEntityType)
        name: Name of the entity
        occurrences: Number of clusters this entity has been found

    Returns:
        KGEntity: The created entity
    """
    entity_type = entity_type.upper()
    name = name.title()
    id_name = f"{entity_type}:{name}"

    _KGEntityObject: Type[KGEntity | KGEntityExtractionStaging]
    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject = KGEntityExtractionStaging
    elif kg_stage == KGStage.NORMALIZED:
        _KGEntityObject = KGEntity
    else:
        raise ValueError(f"Invalid KGStage: {kg_stage}")

    # Create new entity
    stmt = (
        pg_insert(_KGEntityObject)
        .values(
            id_name=id_name,
            entity_type_id_name=entity_type,
            document_id=document_id,
            name=name,
            occurrences=occurrences,
            event_time=event_time,
            attributes=attributes,
        )
        .on_conflict_do_update(
            index_elements=["id_name"],
            set_=dict(
                # Direct numeric addition without text()
                occurrences=_KGEntityObject.occurrences + occurrences,
                # Keep other fields updated as before
                entity_type_id_name=entity_type,
                document_id=document_id,
                name=name,
                event_time=event_time,
                attributes=attributes,
            ),
        )
        .returning(_KGEntityObject)
    )

    result = db_session.execute(stmt).scalar()

    # Update the document's kg_stage if document_id is provided
    if document_id is not None:

        db_session.query(Document).filter(Document.id == document_id).update(
            {"kg_stage": kg_stage}
        )
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


def get_entities_by_grounding(
    db_session: Session, kg_stage: KGStage, grounding: KGGroundingType
) -> List[KGEntity] | List[KGEntityExtractionStaging]:
    """Get all entities by grounding type.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntity objects for a given grounding type
    """

    _KGEntityObject: Type[KGEntity | KGEntityExtractionStaging]

    if kg_stage not in [KGStage.EXTRACTED, KGStage.NORMALIZED]:
        raise ValueError(f"Invalid KGStage: {kg_stage}")

    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject = KGEntityExtractionStaging
    elif kg_stage == KGStage.NORMALIZED:
        _KGEntityObject = KGEntity

    result = list(
        db_session.query(_KGEntityObject)
        .join(
            KGEntityType,
            _KGEntityObject.entity_type_id_name == KGEntityType.id_name,
        )
        .filter(KGEntityType.grounding == grounding)
        .all()
    )

    if kg_stage == KGStage.EXTRACTED:
        return cast(List[KGEntityExtractionStaging], result)
    else:
        return cast(List[KGEntity], result)


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


def delete_entities_by_id_names(
    db_session: Session, id_names: list[str], kg_stage: KGStage
) -> int:
    """
    Delete entities from the database based on a list of id_names.

    Args:
        db_session: SQLAlchemy database session
        id_names: List of entity id_names to delete

    Returns:
        Number of entities deleted
    """

    if kg_stage not in [KGStage.EXTRACTED, KGStage.NORMALIZED]:
        raise ValueError(f"Invalid KGStage: {kg_stage}")

    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject: Type[KGEntity | KGEntityExtractionStaging] = (
            KGEntityExtractionStaging
        )

    elif kg_stage == KGStage.NORMALIZED:
        _KGEntityObject = KGEntity
    deleted_count = (
        db_session.query(_KGEntityObject)
        .filter(_KGEntityObject.id_name.in_(id_names))
        .delete(synchronize_session=False)
    )

    db_session.flush()  # Flush to ensure deletion is processed
    return deleted_count


def get_entity_names_for_types(
    db_session: Session, entity_types: List[str]
) -> List[tuple[str, str | None]]:
    """Get all entities that belong to the specified entity types.

    Args:
        db_session: SQLAlchemy session
        entity_types: List of entity type id_names to filter by

    Returns:
        List of entity id_names belonging to the specified entity types
    """
    entity_query = db_session.query(KGEntity).filter(
        KGEntity.entity_type_id_name.in_(entity_types)
    )

    # Get document IDs from the filtered entities
    doc_ids = [e.document_id for e in entity_query.all() if e.document_id is not None]

    # Get document info for those IDs
    doc_info: dict[str, tuple[str | None, str | None]] = {
        row[0].capitalize(): (row[1], row[2])
        for row in db_session.query(Document.id, Document.semantic_id, Document.link)
        .filter(Document.id.in_(doc_ids))
        .all()
    }

    # Return entities with their document info

    names: list[tuple[str, str | None]] = []
    for entity in entity_query.all():
        if entity.document_id is not None:
            # Extract entity type from the full type ID
            entity_type = entity.entity_type_id_name.split(":")[0].upper()

            # Get document info, defaulting to None if not found
            doc_semantic_id = doc_info.get(
                entity.document_id.capitalize(), (None, None)
            )[0]

            # Construct the final string
            names.append((entity.id_name, f"{entity_type}:{doc_semantic_id}"))
        else:
            names.append((entity.id_name, entity.id_name))

    return names


def get_entities_by_document_ids(
    db_session: Session, document_ids: list[str], kg_stage: KGStage
) -> List[str]:
    """Get all entity id_names that belong to the specified document ids.

    Args:
        db_session: SQLAlchemy database session
        document_ids: List of document ids to filter by

    Returns:
        List of entity id_names belonging to the specified document ids
    """
    if kg_stage == KGStage.EXTRACTED:
        stmt = select(KGEntityExtractionStaging.id_name).where(
            func.lower(KGEntityExtractionStaging.document_id).in_(document_ids)
        )
    elif kg_stage == KGStage.NORMALIZED:
        stmt = select(KGEntity.id_name).where(
            func.lower(KGEntity.document_id).in_(document_ids)
        )
    else:
        raise ValueError(f"Invalid KGStage: {kg_stage.value}")
    result = db_session.execute(stmt).scalars().all()
    return list(result)


def get_document_id_for_entity(
    db_session: Session, entity: str, kg_stage: KGStage = KGStage.NORMALIZED
) -> str | None:
    """Get the document ID associated with an entity.

    Args:
        db_session: SQLAlchemy database session
        entity: The entity id_name to look up
        kg_stage: The knowledge graph stage to search in (defaults to NORMALIZED)

    Returns:
        The document ID if found, None otherwise
    """

    entity = entity.replace(": ", ":")

    if kg_stage == KGStage.EXTRACTED:
        stmt = select(KGEntityExtractionStaging.document_id).where(
            func.lower(KGEntityExtractionStaging.id_name) == func.lower(entity)
        )
    elif kg_stage == KGStage.NORMALIZED:
        stmt = select(KGEntity.document_id).where(
            func.lower(KGEntity.id_name) == func.lower(entity)
        )
    else:
        raise ValueError(f"Invalid KGStage: {kg_stage}")

    result = db_session.execute(stmt).scalars().first()
    return result
