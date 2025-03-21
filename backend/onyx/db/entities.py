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
    cluster_count: int = 0,
) -> "KGEntity":
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
    name = name.capitalize()
    id_name = f"{entity_type}:{name}"

    # Create new entity
    entity = KGEntity(
        id_name=id_name,
        entity_type_id_name=entity_type,
        name=name,
        cluster_count=cluster_count,
    )

    db_session.add(entity)
    db_session.flush()  # Flush to get any DB errors early

    return entity
