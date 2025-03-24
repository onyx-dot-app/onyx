from typing import List

from sqlalchemy import literal_column
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import KGEntity
from onyx.db.models import KGEntityType


def get_entity_types(
    db_session: Session,
    active: bool = True,
) -> list[KGEntityType]:
    # Query the database for all distinct entity types
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.active == active)
        .order_by(KGEntityType.id_name)
        .all()
    )


def add_entity(
    db_session: Session,
    entity_type: str,
    name: str,
    document_id: str | None = None,
    cluster_count: int = 0,
) -> "KGEntity | None":
    """Add a new entity to the database.

    Args:
        db_session: SQLAlchemy session
        entity_type: Type of the entity (must match an existing KGEntityType)
        name: Name of the entity
        cluster_count: Number of clusters this entity has been found

    Returns:
        KGEntity: The created entity
    """
    entity_type = entity_type.upper()
    name = name.title()
    id_name = f"{entity_type}:{name}"

    # Create new entity
    stmt = (
        pg_insert(KGEntity)
        .values(
            id_name=id_name,
            entity_type_id_name=entity_type,
            document_id=document_id,
            name=name,
            cluster_count=cluster_count,
        )
        .on_conflict_do_update(
            index_elements=["id_name"],
            set_=dict(
                # Direct numeric addition without text()
                cluster_count=KGEntity.cluster_count
                + literal_column("EXCLUDED.cluster_count"),
                # Keep other fields updated as before
                entity_type_id_name=entity_type,
                document_id=document_id,
                name=name,
            ),
        )
        .returning(KGEntity)
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
