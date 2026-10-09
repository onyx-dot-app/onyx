from sqlalchemy.orm import Session

from onyx.db.models import (
    KGEntity,
    KGEntityExtractionStaging,
    KGRelationship,
    KGRelationshipExtractionStaging,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
