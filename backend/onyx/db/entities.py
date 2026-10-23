from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.db.entity_type import UNGROUNDED_SOURCE_NAME
from onyx.db.models import KGEntity, KGEntityExtractionStaging, KGEntityType


def delete_from_kg_entities_extraction_staging__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete entities from the extraction staging table."""
    db_session.query(KGEntityExtractionStaging).filter(
        KGEntityExtractionStaging.document_id.in_(document_ids)
    ).delete(synchronize_session=False)


def delete_from_kg_entities__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """Delete entities from the normalized table."""
    db_session.query(KGEntity).filter(KGEntity.document_id.in_(document_ids)).delete(
        synchronize_session=False
    )


def get_entity_stats_by_grounded_source_name(
    db_session: Session,
) -> dict[str, tuple[datetime, int]]:
    """
    Returns a dict mapping each grounded_source_name to a tuple in which:
        - the first element is the latest update time across all entities with the same entity-type
        - the second element is the count of `KGEntity`s
    """
    results = (
        db_session.query(
            KGEntityType.grounded_source_name,
            func.count(KGEntity.id_name).label("entities_count"),
            func.max(KGEntity.time_updated).label("last_updated"),
        )
        .join(KGEntityType, KGEntity.entity_type_id_name == KGEntityType.id_name)
        .group_by(KGEntityType.grounded_source_name)
        .all()
    )

    # `row.grounded_source_name` is NULLABLE in the database schema.
    # Thus, for all "ungrounded" entity-types, we use a default name.
    return {
        (row.grounded_source_name or UNGROUNDED_SOURCE_NAME): (
            row.last_updated,
            row.entities_count,
        )
        for row in results
    }
