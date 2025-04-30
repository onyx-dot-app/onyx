from typing import List

from sqlalchemy.orm import Session

from onyx.db.models import KGEntityType
from onyx.kg.kg_default_entity_definitions import KGDefaultAccountEmployeeDefinitions
from onyx.kg.kg_default_entity_definitions import (
    KGDefaultPrimaryGroundedEntityDefinitions,
)
from onyx.kg.models import KGGroundingType


def get_determined_grounded_entity_types(db_session: Session) -> List[KGEntityType]:
    """Get all entity types that have non-null entity_values.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have entity_values defined
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.entity_values.isnot(None))
        .all()
    )


def get_grounded_entity_types(db_session: Session) -> List[KGEntityType]:
    """Get all entity types that have grounding = GROUNDED.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have grounding = GROUNDED
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounding == KGGroundingType.GROUNDED)
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


def get_entity_type_by_grounded_source_name(
    db_session: Session, grounded_source_name: KGGroundingType
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


def populate_default_primary_grounded_entity_type_information(
    db_session: Session,
) -> None:
    """Populate the entity type information for the KG.

    Args:
        db_session: SQLAlchemy session
    """
    # Get all existing entity types
    existing_entity_types = {et.id_name for et in db_session.query(KGEntityType).all()}

    # Create an instance of the default definitions
    default_definitions = KGDefaultPrimaryGroundedEntityDefinitions()

    # Iterate over all attributes in the default definitions
    for id_name, definition in default_definitions.model_dump().items():
        # Skip if this entity type already exists
        if id_name in existing_entity_types:
            continue

        # Create new entity type
        new_entity_type = KGEntityType(
            id_name=id_name,
            description=definition["description"],
            grounding=definition["grounding"],
            grounded_source_name=id_name.lower(),
            active=False,
        )

        # Add to session
        db_session.add(new_entity_type)

    # Commit changes
    db_session.flush()


def populate_default_employee_account_information(db_session: Session) -> None:
    """Populate the entity type information for the KG.

    Args:
        db_session: SQLAlchemy session
    """
    # Get all existing entity types
    existing_entity_types = {et.id_name for et in db_session.query(KGEntityType).all()}

    # Create an instance of the default definitions
    default_definitions = KGDefaultAccountEmployeeDefinitions()

    # Iterate over all attributes in the default definitions
    for id_name, definition in default_definitions.model_dump().items():
        # Skip if this entity type already exists
        if id_name in existing_entity_types:
            continue

        # Create new entity type
        new_entity_type = KGEntityType(
            id_name=id_name,
            description=definition["description"],
            grounding=definition["grounding"],
            grounded_source_name=id_name,
            active=True,
        )

        # Add to session
        db_session.add(new_entity_type)

    # Commit changes
    db_session.flush()


def get_grounded_entity_types_with_null_grounded_source(
    db_session: Session,
) -> List[KGEntityType]:
    """Get all entity types that have null grounded_source_name and grounding = GROUNDED.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have null grounded_source_name and grounding = GROUNDED
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounded_source_name.is_(None))
        .filter(KGEntityType.grounding == KGGroundingType.GROUNDED)
        .all()
    )


def get_entity_types_by_grounding(
    db_session: Session,
    grounding: KGGroundingType,
) -> List[KGEntityType]:
    """Get all entity types that have a specific grounding.

    Args:
        db_session: SQLAlchemy session
        grounding: The grounding type to filter by

    Returns:
        List of KGEntityType objects that have the specified grounding
    """
    return (
        db_session.query(KGEntityType).filter(KGEntityType.grounding == grounding).all()
    )
