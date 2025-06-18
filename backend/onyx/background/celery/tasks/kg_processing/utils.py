from sqlalchemy.orm import Session

from onyx.db.document import check_for_documents_needing_kg_processing
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import is_kg_config_settings_enabled_valid
from onyx.db.kg_config import is_kg_processing_in_progress
from onyx.db.kg_config import set_kg_processing_in_progress
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationshipExtractionStaging


def is_kg_processing_requirements_met(db_session: Session) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created, and then looks for documents that should be indexed.
    """
    if is_kg_processing_in_progress():
        return False

    kg_config = get_kg_config_settings()
    if not is_kg_config_settings_enabled_valid(kg_config):
        return False

    return check_for_documents_needing_kg_processing(
        db_session, kg_config.KG_COVERAGE_START_DATE, kg_config.KG_MAX_COVERAGE_DAYS
    )


def is_kg_clustering_only_requirements_met(db_session: Session) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created, and then looks for documents that should be indexed.
    """
    if is_kg_processing_in_progress():
        return False

    kg_config = get_kg_config_settings()
    if not is_kg_config_settings_enabled_valid(kg_config):
        return False

    # Check if there are any entries in the staging tables
    has_staging_entities = (
        db_session.query(KGEntityExtractionStaging).first() is not None
    )
    has_staging_relationships = (
        db_session.query(KGRelationshipExtractionStaging).first() is not None
    )

    return has_staging_entities or has_staging_relationships


def block_kg_processing_current_tenant() -> None:
    """Blocks KG processing for a tenant."""
    set_kg_processing_in_progress(in_progress=True)


def unblock_kg_processing_current_tenant() -> None:
    """Blocks KG processing for a tenant."""
    set_kg_processing_in_progress(in_progress=False)
