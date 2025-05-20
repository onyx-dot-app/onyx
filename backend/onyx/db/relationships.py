from typing import cast
from typing import List
from typing import Union

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.models import KGStage
from onyx.kg.utils.formatting_utils import format_entity
from onyx.kg.utils.formatting_utils import format_relationship
from onyx.kg.utils.formatting_utils import generate_relationship_type


def add_relationship(
    db_session: Session,
    kg_stage: KGStage,
    relationship_id_name: str,
    source_document_id: str,
    occurrences: int | None = None,
) -> Union["KGRelationship", "KGRelationshipExtractionStaging"]:
    """
    Add a relationship between two entities to the database.

    Args:
        db_session: SQLAlchemy database session
        relationship_type: Type of relationship
        source_document_id: ID of the source document
        occurrences: Optional count of similar relationships clustered together

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
    source_entity_type = source_entity_id_name.split("::")[0]
    target_entity_id_name = format_entity(target_entity_id_name)
    target_entity_type = target_entity_id_name.split("::")[0]
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
        "occurrences": occurrences or 1,
    }

    relationship: KGRelationship | KGRelationshipExtractionStaging
    if kg_stage == KGStage.EXTRACTED:
        relationship = KGRelationshipExtractionStaging(**relationship_data)
        # Delete existing relationship if it exists
        db_session.query(KGRelationshipExtractionStaging).filter(
            KGRelationshipExtractionStaging.id_name == relationship_id_name,
            KGRelationshipExtractionStaging.source_document == source_document_id,
        ).delete(synchronize_session=False)
    elif kg_stage == KGStage.NORMALIZED:
        relationship = KGRelationship(**relationship_data)
        # Delete existing relationship if it exists
        db_session.query(KGRelationship).filter(
            KGRelationship.id_name == relationship_id_name,
            KGRelationship.source_document == source_document_id,
        ).delete(synchronize_session=False)
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")

    # Insert the new relationship
    stmt = postgresql.insert(type(relationship)).values(**relationship_data)
    db_session.execute(stmt)
    db_session.flush()  # Flush to get any DB errors early

    # Fetch the inserted record
    result: Union[KGRelationship, KGRelationshipExtractionStaging, None] = None
    if kg_stage == KGStage.EXTRACTED:
        result = (
            db_session.query(KGRelationshipExtractionStaging)
            .filter_by(id_name=relationship_id_name, source_document=source_document_id)
            .first()
        )
    else:
        result = (
            db_session.query(KGRelationship)
            .filter_by(id_name=relationship_id_name, source_document=source_document_id)
            .first()
        )

    if result is None:
        raise ValueError(
            f"Failed to create relationship with id_name: {relationship_id_name}"
        )

    return result


def add_or_increment_relationship(
    db_session: Session,
    kg_stage: KGStage,
    relationship_id_name: str,
    source_document_id: str,
    new_occurrences: int = 1,
) -> KGRelationship | KGRelationshipExtractionStaging:
    """
    Add a relationship between two entities to the database if it doesn't exist,
    or increment its occurrences by 1 if it already exists.

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

    _KGTable: type[KGRelationship] | type[KGRelationshipExtractionStaging]
    if kg_stage == KGStage.EXTRACTED:
        _KGTable = KGRelationshipExtractionStaging
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
        # If it exists, increment the occurrences
        existing_relationship = cast(
            KGRelationship | KGRelationshipExtractionStaging, existing_relationship
        )
        existing_relationship.occurrences = (
            existing_relationship.occurrences or 0
        ) + new_occurrences
        db_session.flush()
        return existing_relationship
    else:
        # If it doesn't exist, add it with occurrences=1
        db_session.flush()
        return add_relationship(
            db_session,
            KGStage(kg_stage),
            relationship_id_name,
            source_document_id,
            occurrences=new_occurrences,
        )


def add_relationship_type(
    db_session: Session,
    kg_stage: KGStage,
    source_entity_type: str,
    relationship_type: str,
    target_entity_type: str,
    definition: bool = False,
    extraction_count: int = 0,
) -> str:
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
        "occurrences": extraction_count,
        "type": relationship_type,  # Using the relationship_type as the type
        "active": True,  # Setting as active by default
    }

    rel_type: KGRelationshipType | KGRelationshipTypeExtractionStaging

    if kg_stage == KGStage.EXTRACTED:
        rel_type = KGRelationshipTypeExtractionStaging(**relationship_data)
    elif kg_stage == KGStage.NORMALIZED:
        rel_type = KGRelationshipType(**relationship_data)
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")

    # Use on_conflict_do_update to handle conflicts
    stmt = (
        postgresql.insert(type(rel_type))
        .values(**relationship_data)
        .on_conflict_do_update(
            index_elements=["id_name"],
            set_={
                "name": relationship_data["name"],
                "source_entity_type_id_name": relationship_data[
                    "source_entity_type_id_name"
                ],
                "target_entity_type_id_name": relationship_data[
                    "target_entity_type_id_name"
                ],
                "definition": relationship_data["definition"],
                "occurrences": int(str(relationship_data["occurrences"] or 0))
                + extraction_count,
                "type": relationship_data["type"],
                "active": relationship_data["active"],
                "time_updated": func.now(),
            },
        )
    )

    db_session.execute(stmt)
    db_session.flush()  # Flush to get any DB errors early

    return id_name


def get_all_relationship_types(
    db_session: Session, kg_stage: str
) -> list["KGRelationshipType"] | list["KGRelationshipTypeExtractionStaging"]:
    """
    Retrieve all relationship types from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        List of KGRelationshipType or KGRelationshipTypeExtractionStaging objects
    """
    if kg_stage == KGStage.EXTRACTED:
        return db_session.query(KGRelationshipTypeExtractionStaging).all()
    elif kg_stage == KGStage.NORMALIZED:
        return db_session.query(KGRelationshipType).all()
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")


def get_all_relationships(
    db_session: Session, kg_stage: KGStage
) -> list["KGRelationship"] | list["KGRelationshipExtractionStaging"]:
    """
    Retrieve all relationships from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        List of KGRelationship objects
    """
    if kg_stage == KGStage.EXTRACTED:
        return db_session.query(KGRelationshipExtractionStaging).all()
    elif kg_stage == KGStage.NORMALIZED:
        return db_session.query(KGRelationship).all()
    else:
        raise ValueError(f"Invalid kg_stage: {kg_stage}")


def delete_relationships_by_id_names(
    db_session: Session, id_names: list[str], kg_stage: KGStage
) -> int:
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

    deleted_count = 0

    if kg_stage == KGStage.EXTRACTED:
        deleted_count = (
            db_session.query(KGRelationshipExtractionStaging)
            .filter(KGRelationshipExtractionStaging.id_name.in_(id_names))
            .delete(synchronize_session=False)
        )
    elif kg_stage == KGStage.NORMALIZED:
        deleted_count = (
            db_session.query(KGRelationship)
            .filter(KGRelationship.id_name.in_(id_names))
            .delete(synchronize_session=False)
        )

    db_session.flush()  # Flush to ensure deletion is processed
    return deleted_count


def delete_relationship_types_by_id_names(
    db_session: Session, id_names: list[str], kg_stage: KGStage
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
    deleted_count = 0

    if kg_stage == KGStage.EXTRACTED:
        deleted_count = (
            db_session.query(KGRelationshipTypeExtractionStaging)
            .filter(KGRelationshipTypeExtractionStaging.id_name.in_(id_names))
            .delete(synchronize_session=False)
        )
    elif kg_stage == KGStage.NORMALIZED:
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
    entity_types = list(set([entity.split("::")[0] for entity in entities]))

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


def get_relationship_types_of_entity_types(
    db_session: Session, entity_types_id: str
) -> List[str]:
    """Get all relationship ID names where the given entity is either the source or target node.

    Args:
        db_session: SQLAlchemy session
        entity_types_id: ID of the entity to find relationships for

    Returns:
        List of relationship ID names where the entity is either source or target
    """

    if entity_types_id.endswith(":*"):
        entity_types_id = entity_types_id[:-2]

    return [
        row[0]
        for row in (
            db_session.query(KGRelationshipType.id_name)
            .filter(
                or_(
                    KGRelationshipType.source_entity_type_id_name == entity_types_id,
                    KGRelationshipType.target_entity_type_id_name == entity_types_id,
                )
            )
            .all()
        )
    ]


def delete_document_references_from_kg(db_session: Session, document_id: str) -> None:
    # Delete relationships from normalized stage
    db_session.query(KGRelationship).filter(
        KGRelationship.source_document == document_id
    ).delete(synchronize_session=False)

    # Delete relationships from extraction staging
    db_session.query(KGRelationshipExtractionStaging).filter(
        KGRelationshipExtractionStaging.source_document == document_id
    ).delete(synchronize_session=False)

    # Delete entities from normalized stage
    db_session.query(KGEntity).filter(KGEntity.document_id == document_id).delete(
        synchronize_session=False
    )

    # Delete entities from extraction staging
    db_session.query(KGEntityExtractionStaging).filter(
        KGEntityExtractionStaging.document_id == document_id
    ).delete(synchronize_session=False)

    db_session.flush()


def delete_from_kg_relationships_extraction_staging__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete relationships from the extraction staging table."""
    db_session.query(KGRelationshipExtractionStaging).filter(
        KGRelationshipExtractionStaging.source_document.in_(document_ids)
    ).delete(synchronize_session=False)


def delete_from_kg_relationships__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete relationships from the normalized table."""
    db_session.query(KGRelationship).filter(
        KGRelationship.source_document.in_(document_ids)
    ).delete(synchronize_session=False)
