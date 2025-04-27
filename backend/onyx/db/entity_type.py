from typing import List

from sqlalchemy.orm import Session

from onyx.db.models import KGEntityType


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
