from sqlalchemy.orm import Session

from onyx.db.document import check_for_documents_needing_kg_processing
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import KGProcessingType
from onyx.db.kg_config import set_kg_processing_in_progress_status
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationshipExtractionStaging


def _update_kg_processing_status(db_session: Session, status_update: bool) -> None:
    """Updates KG processing status for a tenant. (tenant implied by db_session)"""

    set_kg_processing_in_progress_status(
        db_session,
        processing_type=KGProcessingType.EXTRACTION,
        in_progress=status_update,
    )

    set_kg_processing_in_progress_status(
        db_session,
        processing_type=KGProcessingType.CLUSTERING,
        in_progress=status_update,
    )


def is_kg_processing_unblocked(db_session: Session) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created.
    """

    kg_config = get_kg_config_settings(db_session)
    return kg_config.KG_ENABLED and not (
        kg_config.KG_EXTRACTION_IN_PROGRESS or kg_config.KG_CLUSTERING_IN_PROGRESS
    )


def is_kg_processing_requirements_met(db_session: Session) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created, and then looks for documents that should be indexed.
    """
    if not is_kg_processing_unblocked(db_session):
        return False

    kg_config = get_kg_config_settings(db_session)
    return check_for_documents_needing_kg_processing(
        db_session, kg_config.KG_COVERAGE_START, kg_config.KG_MAX_COVERAGE_DAYS
    )


def is_kg_clustering_only_requirements_met(db_session: Session) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created, and then looks for documents that should be indexed.
    """
    if not is_kg_processing_unblocked(db_session):
        return False

    # Check if there are any entries in the staging tables
    has_staging_entities = (
        db_session.query(KGEntityExtractionStaging).first() is not None
    )
    has_staging_relationships = (
        db_session.query(KGRelationshipExtractionStaging).first() is not None
    )

    return has_staging_entities or has_staging_relationships


def block_kg_processing_current_tenant(db_session: Session) -> None:
    """Blocks KG processing for a tenant."""
    _update_kg_processing_status(db_session, True)


def unblock_kg_processing_current_tenant(db_session: Session) -> None:
    """Blocks KG processing for a tenant."""
    _update_kg_processing_status(db_session, False)
