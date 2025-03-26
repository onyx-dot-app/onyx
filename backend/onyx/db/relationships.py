from sqlalchemy import or_
from sqlalchemy.orm import Session

from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipType
from onyx.kg.utils.formatting_utils import format_entity
from onyx.kg.utils.formatting_utils import format_relationship
from onyx.kg.utils.formatting_utils import generate_relationship_type


def add_relationship(
    db_session: Session,
    relationship_id_name: str,
    cluster_count: int | None = None,
) -> "KGRelationship":
    """
    Add a relationship between two entities to the database.

    Args:
        db_session: SQLAlchemy database session
        source_entity_id: ID of the source entity
        relationship_type: Type of relationship
        target_entity_id: ID of the target entity
        cluster_count: Optional count of similar relationships clustered together

    Returns:
        The created KGRelationship object

    Raises:
        sqlalchemy.exc.IntegrityError: If the relationship already exists or entities don't exist
    """
    # Generate a unique ID for the relationship

    (
        source_entity_id_name,
        relationship_string,
        target_entity_id_name,
    ) = relationship_id_name.split("__")

    source_entity_id_name = format_entity(source_entity_id_name)
    target_entity_id_name = format_entity(target_entity_id_name)
    relationship_id_name = format_relationship(relationship_id_name)
    relationship_type = generate_relationship_type(relationship_id_name)

    # Create new relationship
    relationship = KGRelationship(
        id_name=relationship_id_name,
        source_node=source_entity_id_name,
        target_node=target_entity_id_name,
        type=relationship_string.lower(),
        relationship_type_id_name=relationship_type,
        cluster_count=cluster_count,
    )

    db_session.add(relationship)
    db_session.flush()  # Flush to get any DB errors early

    return relationship


def add_relationship_type(
    db_session: Session,
    source_entity_type: str,
    relationship_type: str,
    target_entity_type: str,
    definition: bool = False,
    extraction_count: int = 0,
) -> "KGRelationshipType":
    """
    Add a new relationship type to the database.

    Args:
        db_session: SQLAlchemy session
        source_entity_type: Type of the source entity
        relationship_type: Type of relationship
        target_entity_type: Type of the target entity
        definition: Whether this relationship type represents a definition (default False)

    Returns:
        The created KGRelationshipType object

    Raises:
        sqlalchemy.exc.IntegrityError: If the relationship type already exists
    """

    id_name = f"{source_entity_type.upper()}__{relationship_type}__{target_entity_type.upper()}"
    # Create new relationship type
    rel_type = KGRelationshipType(
        id_name=id_name,
        name=relationship_type,
        source_entity_type_id_name=source_entity_type.upper(),
        target_entity_type_id_name=target_entity_type.upper(),
        definition=definition,
        cluster_count=extraction_count,
        type=relationship_type,  # Using the relationship_type as the type
        active=True,  # Setting as active by default
    )

    db_session.add(rel_type)
    db_session.flush()  # Flush to get any DB errors early

    return rel_type


def get_all_relationship_types(db_session: Session) -> list["KGRelationshipType"]:
    """
    Retrieve all relationship types from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        List of KGRelationshipType objects
    """
    return db_session.query(KGRelationshipType).all()


def get_all_relationships(db_session: Session) -> list["KGRelationship"]:
    """
    Retrieve all relationships from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        List of KGRelationship objects
    """
    return db_session.query(KGRelationship).all()


def delete_relationships_by_id_names(db_session: Session, id_names: list[str]) -> int:
    """
    Delete relationships from the database based on a list of id_names.

    Args:
        db_session: SQLAlchemy database session
        id_names: List of relationship id_names to delete

    Returns:
        Number of relationships deleted

    Raises:
        sqlalchemy.exc.SQLAlchemyError: If there's an error during deletion
    """
    deleted_count = (
        db_session.query(KGRelationship)
        .filter(KGRelationship.id_name.in_(id_names))
        .delete(synchronize_session=False)
    )

    db_session.flush()  # Flush to ensure deletion is processed
    return deleted_count


def delete_relationship_types_by_id_names(
    db_session: Session, id_names: list[str]
) -> int:
    """
    Delete relationship types from the database based on a list of id_names.

    Args:
        db_session: SQLAlchemy database session
        id_names: List of relationship type id_names to delete

    Returns:
        Number of relationship types deleted

    Raises:
        sqlalchemy.exc.SQLAlchemyError: If there's an error during deletion
    """
    deleted_count = (
        db_session.query(KGRelationshipType)
        .filter(KGRelationshipType.id_name.in_(id_names))
        .delete(synchronize_session=False)
    )

    db_session.flush()  # Flush to ensure deletion is processed
    return deleted_count


def get_relationships_for_entity_type_pairs(
    db_session: Session, entity_type_pairs: list[tuple[str, str]]
) -> list["KGRelationshipType"]:
    """
    Get relationship types from the database based on a list of entity type pairs.

    Args:
        db_session: SQLAlchemy database session
        entity_type_pairs: List of tuples where each tuple contains (source_entity_type, target_entity_type)

    Returns:
        List of KGRelationshipType objects where source and target types match the provided pairs
    """

    conditions = [
        (
            (KGRelationshipType.source_entity_type_id_name == source_type)
            & (KGRelationshipType.target_entity_type_id_name == target_type)
        )
        for source_type, target_type in entity_type_pairs
    ]

    return db_session.query(KGRelationshipType).filter(or_(*conditions)).all()
