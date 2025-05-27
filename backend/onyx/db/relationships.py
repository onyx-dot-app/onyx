from typing import List
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

import onyx.db.document as dbdocument
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


def add_or_update_staging_relationship(
    db_session: Session,
    relationship_id_name: str,
    source_document_id: str,
    occurrences: int = 1,
) -> KGRelationshipExtractionStaging:
    """
    Add or update a new staging relationship to the database.

    Args:
        db_session: SQLAlchemy database session
        relationship_id_name: The ID name of the relationship in format "source__relationship__target"
        source_document_id: ID of the source document
        occurrences: Number of times this relationship has been found
    Returns:
        The created or updated KGRelationshipExtractionStaging object

    Raises:
        sqlalchemy.exc.IntegrityError: If there's an error with the database operation
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

    # Insert the new relationship
    stmt = (
        postgresql.insert(KGRelationshipExtractionStaging)
        .values(
            {
                "id_name": relationship_id_name,
                "source_node": source_entity_id_name,
                "target_node": target_entity_id_name,
                "source_node_type": source_entity_type,
                "target_node_type": target_entity_type,
                "type": relationship_string.lower(),
                "relationship_type_id_name": relationship_type,
                "source_document": source_document_id,
                "occurrences": occurrences,
            }
        )
        .on_conflict_do_update(
            index_elements=["id_name", "source_document"],
            set_={
                "id_name": relationship_id_name,
                "source_node": source_entity_id_name,
                "target_node": target_entity_id_name,
                "source_node_type": source_entity_type,
                "target_node_type": target_entity_type,
                "type": relationship_string.lower(),
                "relationship_type_id_name": relationship_type,
                "source_document": source_document_id,
                "occurrences": KGRelationshipExtractionStaging.occurrences
                + occurrences,
            },
        )
        .returning(KGRelationshipExtractionStaging)
    )

    result = db_session.execute(stmt).scalar()
    if result is None:
        raise RuntimeError(
            f"Failed to create or increment relationship with id_name: {relationship_id_name}"
        )

    # Update the document's kg_stage if source_document is provided
    if source_document_id is not None:
        dbdocument.update_document_kg_info(
            db_session,
            document_id=source_document_id,
            kg_stage=KGStage.EXTRACTED,
        )
    db_session.flush()  # Flush to get any DB errors early

    return result


def transfer_relationship(
    db_session: Session,
    relationship: KGRelationshipExtractionStaging,
    entity_translations: dict[str, UUID],
) -> KGRelationship:
    """
    Transfer a relationship from the staging table to the normalized table.
    """
    # Translate the source and target nodes
    source_node = entity_translations[relationship.source_node]
    target_node = entity_translations[relationship.target_node]
    relationship_id_name = f"{source_node}__{relationship.type}__{target_node}"

    # Create the transferred relationship
    relationship = KGRelationship(
        id_name=relationship_id_name,
        source_node=source_node,
        target_node=target_node,
        source_node_type=relationship.source_node_type,
        target_node_type=relationship.target_node_type,
        type=relationship.type,
        relationship_type_id_name=relationship.relationship_type_id_name,
        source_document=relationship.source_document,
        occurrences=relationship.occurrences or 1,
    )
    db_session.add(relationship)

    # Update the document's kg_stage if source_document is provided
    if relationship.source_document is not None:
        dbdocument.update_document_kg_info(
            db_session,
            document_id=relationship.source_document,
            kg_stage=KGStage.NORMALIZED,
        )
        # TODO: update vespa
    db_session.flush()

    return relationship


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
