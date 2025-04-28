from datetime import datetime
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
    occurances: int = 0,
    event_time: datetime | None = None,
    attributes: dict[str, str] | None = None,
) -> "KGEntity | KGEntityExtractionStaging | None":
    """Add a new entity to the database.

    Args:
        db_session: SQLAlchemy session
        kg_stage: KGStage of the entity
        entity_type: Type of the entity (must match an existing KGEntityType)
        name: Name of the entity
        occurances: Number of clusters this entity has been found

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
            occurances=occurances,
            event_time=event_time,
            attributes=attributes,
        )
        .on_conflict_do_update(
            index_elements=["id_name"],
            set_=dict(
                # Direct numeric addition without text()
                occurances=_KGEntityObject.occurances + occurances,
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

    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject = KGEntityExtractionStaging
        return (
            db_session.query(_KGEntityObject)
            .join(
                KGEntityType,
                _KGEntityObject.entity_type_id_name == KGEntityType.id_name,
            )
            .filter(KGEntityType.grounding == grounding)
            .all()
        )
    elif kg_stage == KGStage.NORMALIZED:
        _KGEntityObject = KGEntity
        return (
            db_session.query(_KGEntityObject)
            .join(
                KGEntityType,
                _KGEntityObject.entity_type_id_name == KGEntityType.id_name,
            )
            .filter(KGEntityType.grounding == grounding)
            .all()
        )
    else:
        raise ValueError(f"Invalid KGStage: {kg_stage.value}")


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


def delete_entities_by_id_names(db_session: Session, id_names: list[str]) -> int:
    """
    Delete entities from the database based on a list of id_names.

    Args:
        db_session: SQLAlchemy database session
        id_names: List of entity id_names to delete

    Returns:
        Number of entities deleted
    """
    deleted_count = (
        db_session.query(KGEntity)
        .filter(KGEntity.id_name.in_(id_names))
        .delete(synchronize_session=False)
    )

    db_session.flush()  # Flush to ensure deletion is processed
    return deleted_count


def get_entities_for_types(
    db_session: Session, entity_types: List[str]
) -> List[KGEntity]:
    """Get all entities that belong to the specified entity types.

    Args:
        db_session: SQLAlchemy session
        entity_types: List of entity type id_names to filter by

    Returns:
        List of KGEntity objects belonging to the specified entity types
    """
    return (
        db_session.query(KGEntity)
        .join(KGEntityType, KGEntity.entity_type_id_name == KGEntityType.id_name)
        .filter(KGEntity.entity_type_id_name.in_(entity_types))
        .all()
    )


def get_entities_by_document_ids(
    db_session: Session, document_ids: list[str]
) -> List[str]:
    """Get all entity id_names that belong to the specified document ids.

    Args:
        db_session: SQLAlchemy database session
        document_ids: List of document ids to filter by

    Returns:
        List of entity id_names belonging to the specified document ids
    """
    document_ids = [id.lower() for id in document_ids]
    stmt = select(KGEntity.id_name).where(
        func.lower(KGEntity.document_id).in_(document_ids)
    )
    result = db_session.execute(stmt).scalars().all()
    return list(result)
