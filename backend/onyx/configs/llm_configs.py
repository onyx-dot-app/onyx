from onyx.configs.app_configs import DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB
from onyx.server.settings.store import load_settings


def get_image_extraction_and_analysis_enabled() -> bool:
    """Get image extraction and analysis enabled setting from workspace settings or fallback to False"""
    try:
        settings = load_settings()
        if settings.image_extraction_and_analysis_enabled is not None:
            return settings.image_extraction_and_analysis_enabled
    except Exception:
        pass

    return False


def get_search_time_image_analysis_enabled() -> bool:
    """Get search time image analysis enabled setting from workspace settings or fallback to False"""
    try:
        settings = load_settings()
        if settings.search_time_image_analysis_enabled is not None:
            return settings.search_time_image_analysis_enabled
    except Exception:
        pass

    return False


def get_image_analysis_max_size_mb() -> int:
    """Get image analysis max size MB setting from workspace settings or fallback to environment variable"""
    try:
        settings = load_settings()
        if settings.image_analysis_max_size_mb is not None:
            return settings.image_analysis_max_size_mb
    except Exception:
        pass

    return DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB
