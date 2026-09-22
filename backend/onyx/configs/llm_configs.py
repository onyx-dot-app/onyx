from onyx.configs.app_configs import DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.image_processing import fetch_image_processing_settings


def get_image_extraction_and_analysis_enabled() -> bool:
    """True when the tenant has an image processing row.

    The row is the on switch: no row means no extraction and no captioning.
    Fails closed when the DB cannot be reached (e.g. unit tests without one).
    """
    try:
        with get_session_with_current_tenant() as db_session:
            return fetch_image_processing_settings(db_session) is not None
    except Exception:
        return False


def get_image_analysis_max_size_mb() -> int:
    """The configured max image size, or the default when the feature is off."""
    try:
        with get_session_with_current_tenant() as db_session:
            settings = fetch_image_processing_settings(db_session)
            if settings is not None:
                return settings.max_size_mb
    except Exception:
        pass

    return DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB
