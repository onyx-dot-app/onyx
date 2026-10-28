from onyx.server.settings.store import load_settings


def get_image_extraction_and_analysis_enabled() -> bool:
    """Return the workspace setting for image extraction/analysis.

    The pydantic `Settings` model defaults this field to True, so production
    tenants get the feature on by default on first read. The fallback here
    stays False so environments where settings cannot be loaded at all
    (e.g. unit tests with no DB/Redis) don't trigger downstream vision-LLM
    code paths that assume the DB is reachable.
    """
    try:
        settings = load_settings()
        if settings.image_extraction_and_analysis_enabled is not None:
            return settings.image_extraction_and_analysis_enabled
    except Exception:
        pass

    return False
