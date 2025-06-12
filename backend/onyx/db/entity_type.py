from typing import List

from sqlalchemy.orm import Session

from onyx.db.models import KGEntityType


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
