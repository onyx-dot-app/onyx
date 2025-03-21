from sqlalchemy.orm import Session

from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipType


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
        relationship_type,
        target_entity_id_name,
    ) = relationship_id_name.split("__")

    # Create new relationship
    relationship = KGRelationship(
        id_name=relationship_id_name,
        source_node=source_entity_id_name,
        target_node=target_entity_id_name,
        type=relationship_type,
        relationship_type_id_name=relationship_type,  # Assuming type matches relationship_type_id_name
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
