from datetime import datetime
from typing import List
from typing import Type

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionTemp
from onyx.db.models import KGEntityType
from onyx.kg.models import KGStage


def get_entity_types(
    db_session: Session,
    active: bool | None = True,
) -> list[KGEntityType]:
    # Query the database for all distinct entity types

    if active is None:
        return db_session.query(KGEntityType).order_by(KGEntityType.id_name).all()

    else:
        return (
            db_session.query(KGEntityType)
            .filter(KGEntityType.active == active)
            .order_by(KGEntityType.id_name)
            .all()
        )


def add_entity(
    db_session: Session,
    kg_stage: KGStage,
    entity_type: str,
    name: str,
    document_id: str | None = None,
    occurances: int = 0,
    event_time: datetime | None = None,
    attributes: dict[str, str] | None = None,
) -> "KGEntity | KGEntityExtractionTemp | None":
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

    _KGEntityObject: Type[KGEntity | KGEntityExtractionTemp]
    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject = KGEntityExtractionTemp
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


def get_ungrounded_entities(db_session: Session) -> List[KGEntity]:
    """Get all entities whose entity type has grounding = 'UE' (ungrounded entities).

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntity objects belonging to ungrounded entity types
    """
    return (
        db_session.query(KGEntity)
        .join(KGEntityType, KGEntity.entity_type_id_name == KGEntityType.id_name)
        .filter(KGEntityType.grounding == "UE")
        .all()
    )


def get_entities_by_grounding(
    db_session: Session, kg_stage: KGStage, grounding: str
) -> List[KGEntity] | List[KGEntityExtractionTemp]:
    """Get all entities whose entity type has grounding = 'UE' (ungrounded entities).

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntity objects belonging to ungrounded entity types
    """

    _KGEntityObject: Type[KGEntity | KGEntityExtractionTemp]

    if kg_stage == KGStage.EXTRACTED:
        _KGEntityObject = KGEntityExtractionTemp
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


def get_determined_grounded_entity_types(db_session: Session) -> List[KGEntityType]:
    """Get all entity types that have non-null ge_determine_instructions.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have ge_determine_instructions defined
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.ge_determine_instructions.isnot(None))
        .all()
    )


def get_entity_types_with_grounded_source_name(
    db_session: Session,
) -> List[KGEntityType]:
    """Get all entity types that have non-null grounded_source_name.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have grounded_source_name defined
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounded_source_name.isnot(None))
        .all()
    )


def get_entity_types_with_grounding_signature(
    db_session: Session,
) -> List[KGEntityType]:
    """Get all entity types that have non-null ge_grounding_signature.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have ge_grounding_signature defined
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.ge_grounding_signature.isnot(None))
        .all()
    )


def get_ge_entities_by_types(
    db_session: Session, entity_types: List[str]
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
        .filter(KGEntityType.grounding == "GE")
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


def get_entity_type_by_grounded_source_name(
    db_session: Session, grounded_source_name: str
) -> KGEntityType | None:
    """Get an entity type by its grounded_source_name and return it as a dictionary.

    Args:
        db_session: SQLAlchemy session
        grounded_source_name: The grounded_source_name of the entity to retrieve

    Returns:
        Dictionary containing the entity's data with column names as keys,
        or None if the entity is not found
    """
    entity_type = (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounded_source_name == grounded_source_name)
        .first()
    )

    if entity_type is None:
        return None

    return entity_type
