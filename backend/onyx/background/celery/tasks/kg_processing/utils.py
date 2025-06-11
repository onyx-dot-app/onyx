
from onyx.background.celery.apps.app_base import task_logger

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.document import check_for_documents_needing_kg_processing
from onyx.db.kg_config import set_kg_processing_in_progress_status
from onyx.db.kg_config import KGProcessingType


def _update_kg_processing_status(status_update: bool) -> None:
    """Updates KG processing status for a tenant. (tenant implied by db_session)"""
    with get_session_with_current_tenant() as db_session:
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
        db_session.commit()


def check_kg_processing_unblocked(tenant_id: str
) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created.
    """
    with get_session_with_current_tenant() as db_session:

        kg_config = get_kg_config_settings(db_session)

        if not kg_config.KG_ENABLED:
            return False

        kg_extraction_in_progress = kg_config.KG_EXTRACTION_IN_PROGRESS
        kg_clustering_in_progress = kg_config.KG_CLUSTERING_IN_PROGRESS

    if kg_extraction_in_progress or kg_clustering_in_progress:
        return False

    return True 

def check_kg_processing_requirements(tenant_id: str
) -> bool:
    """Checks for any conditions that should block the KG processing task from being
    created, and then looks for documents that should be indexed.
    """
    if not check_kg_processing_unblocked(tenant_id):
        return False

    with get_session_with_current_tenant() as db_session:

        kg_config = get_kg_config_settings(db_session)

        kg_coverage_start = kg_config.KG_COVERAGE_START
        kg_max_coverage_days = kg_config.KG_MAX_COVERAGE_DAYS

        documents_needing_kg_processing = check_for_documents_needing_kg_processing(
            db_session, kg_coverage_start, kg_max_coverage_days
        )
        

    if not documents_needing_kg_processing:
        return False

    return True 

def block_kg_processing_current_tenant() -> None:
    """Blocks KG processing for a tenant."""
    _update_kg_processing_status(True)

    return None

def unblock_kg_processing_current_tenant() -> None:
    """Blocks KG processing for a tenant."""
    _update_kg_processing_status(False)

    return None
