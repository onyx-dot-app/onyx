from sqlalchemy.orm import Session

from onyx.db.models import KGEntityType


def get_entity_types(
    db_session: Session,
    active: bool = True,
) -> list[KGEntityType]:
    # Query the database for all distinct entity types
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.active == active)
        .order_by(KGEntityType.name)
        .all()
    )
