from typing import cast
from typing import List
from typing import Union

from sqlalchemy import or_
from sqlalchemy.orm import Session

from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionTemp
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionTemp
from onyx.db.models import KGStage
from onyx.kg.utils.formatting_utils import format_entity
from onyx.kg.utils.formatting_utils import format_relationship
from onyx.kg.utils.formatting_utils import generate_relationship_type


def add_relationship(
    db_session: Session,
    kg_stage: KGStage,
    relationship_id_name: str,
    source_document_id: str,
    occurances: int | None = None,
) -> Union["KGRelationship", "KGRelationshipExtractionTemp"]:
    """
    Add a relationship between two entities to the database.

    Args:
        db_session: SQLAlchemy database session
        relationship_type: Type of relationship
        source_document_id: ID of the source document
        occurances: Optional count of similar relationships clustered together

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
    source_entity_type = source_entity_id_name.split(":")[0]
    target_entity_id_name = format_entity(target_entity_id_name)
    target_entity_type = target_entity_id_name.split(":")[0]
    relationship_id_name = format_relationship(relationship_id_name)
    relationship_type = generate_relationship_type(relationship_id_name)

    relationship_data = {
        "id_name": relationship_id_name,
        "source_node": source_entity_id_name,
        "target_node": target_entity_id_name,
        "source_node_type": source_entity_type,
        "target_node_type": target_entity_type,
        "type": relationship_string.lower(),
        "relationship_type_id_name": relationship_type,
        "source_document": source_document_id,
        "occurances": occurances,
    }

    relationship: KGRelationship | KGRelationshipExtractionTemp
    if kg_stage == KGStage.EXTRACTED:
        relationship = KGRelationshipExtractionTemp(**relationship_data)
    elif kg_stage == KGStage.NORMALIZED:
        relationship = KGRelationship(**relationship_data)
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")

    db_session.add(relationship)
    db_session.flush()  # Flush to get any DB errors early

    return relationship


def add_or_increment_relationship(
    db_session: Session,
    kg_stage: KGStage,
    relationship_id_name: str,
    source_document_id: str,
    new_occurances: int = 1,
) -> KGRelationship | KGRelationshipExtractionTemp:
    """
    Add a relationship between two entities to the database if it doesn't exist,
    or increment its occurances by 1 if it already exists.

    Args:
        db_session: SQLAlchemy database session
        relationship_id_name: The ID name of the relationship in format "source__relationship__target"
        source_document_id: ID of the source document
    Returns:
        The created or updated KGRelationship object

    Raises:
        sqlalchemy.exc.IntegrityError: If there's an error with the database operation
    """
    # Format the relationship_id_name
    relationship_id_name = format_relationship(relationship_id_name)

    _KGTable: type[KGRelationship] | type[KGRelationshipExtractionTemp]
    if kg_stage == KGStage.EXTRACTED:
        _KGTable = KGRelationshipExtractionTemp
    elif kg_stage == KGStage.NORMALIZED:
        _KGTable = KGRelationship
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")

    # Check if the relationship already exists
    existing_relationship = (
        db_session.query(_KGTable)
        .filter(_KGTable.id_name == relationship_id_name)
        .filter(_KGTable.source_document == source_document_id)
        .first()
    )

    if existing_relationship:
        # If it exists, increment the occurances
        existing_relationship = cast(
            KGRelationship | KGRelationshipExtractionTemp, existing_relationship
        )
        existing_relationship.occurances = (
            existing_relationship.occurances or 0
        ) + new_occurances
        db_session.flush()
        return existing_relationship
    else:
        # If it doesn't exist, add it with occurances=1
        db_session.flush()
        return add_relationship(
            db_session,
            KGStage(kg_stage),
            relationship_id_name,
            source_document_id,
            occurances=new_occurances,
        )


def add_relationship_type(
    db_session: Session,
    kg_stage: KGStage,
    source_entity_type: str,
    relationship_type: str,
    target_entity_type: str,
    definition: bool = False,
    extraction_count: int = 0,
) -> Union["KGRelationshipType", "KGRelationshipExtractionTemp"]:
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

    relationship_data = {
        "id_name": id_name,
        "name": relationship_type,
        "source_entity_type_id_name": source_entity_type.upper(),
        "target_entity_type_id_name": target_entity_type.upper(),
        "definition": definition,
        "occurances": extraction_count,
        "type": relationship_type,  # Using the relationship_type as the type
        "active": True,  # Setting as active by default
    }

    rel_type: KGRelationshipType | KGRelationshipTypeExtractionTemp

    if kg_stage == KGStage.EXTRACTED:
        rel_type = KGRelationshipTypeExtractionTemp(**relationship_data)
    elif kg_stage == KGStage.NORMALIZED:
        rel_type = KGRelationshipType(**relationship_data)
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")

    db_session.add(rel_type)
    db_session.flush()  # Flush to get any DB errors early

    return rel_type


def get_all_relationship_types(
    db_session: Session, kg_stage: str
) -> list["KGRelationshipType"] | list["KGRelationshipExtractionTemp"]:
    """
    Retrieve all relationship types from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        List of KGRelationshipType or KGRelationshipExtractionTemp objects
    """
    if kg_stage == KGStage.EXTRACTED:
        return db_session.query(KGRelationshipExtractionTemp).all()
    elif kg_stage == KGStage.NORMALIZED:
        return db_session.query(KGRelationshipType).all()
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")


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


def get_allowed_relationship_type_pairs(
    db_session: Session, entities: list[str]
) -> list[str]:
    """
    Get the allowed relationship pairs for the given entities.

    Args:
        db_session: SQLAlchemy database session
        entities: List of entity type ID names to filter by

    Returns:
        List of id_names from KGRelationshipType where both source and target entity types
        are in the provided entities list
    """
    entity_types = list(set([entity.split(":")[0] for entity in entities]))

    return [
        row[0]
        for row in (
            db_session.query(KGRelationshipType.id_name)
            .filter(KGRelationshipType.source_entity_type_id_name.in_(entity_types))
            .filter(KGRelationshipType.target_entity_type_id_name.in_(entity_types))
            .distinct()
            .all()
        )
    ]


def get_relationships_of_entity(db_session: Session, entity_id: str) -> List[str]:
    """Get all relationship ID names where the given entity is either the source or target node.

    Args:
        db_session: SQLAlchemy session
        entity_id: ID of the entity to find relationships for

    Returns:
        List of relationship ID names where the entity is either source or target
    """
    return [
        row[0]
        for row in (
            db_session.query(KGRelationship.id_name)
            .filter(
                or_(
                    KGRelationship.source_node == entity_id,
                    KGRelationship.target_node == entity_id,
                )
            )
            .all()
        )
    ]
