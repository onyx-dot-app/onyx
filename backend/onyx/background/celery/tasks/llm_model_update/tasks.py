from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_AUTO_LLM_UPDATE,
    ignore_result=True,
    soft_time_limit=300,  # 5 minute timeout
    trail=False,
    bind=True,
)
def check_for_auto_llm_updates(self: Task, *, tenant_id: str) -> bool | None:
    """Periodic task to fetch LLM model updates from GitHub
    and sync them to providers in Auto mode.

    This task checks the GitHub-hosted config file and updates all
    providers that have is_auto_mode=True.
    """
    if not AUTO_LLM_CONFIG_URL:
        task_logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping")
        return None

    try:
        # Import here to avoid circular imports
        from onyx.llm.well_known_providers.auto_update_service import (
            fetch_llm_recommendations_from_github,
        )
        from onyx.llm.well_known_providers.auto_update_service import (
            sync_llm_models_from_github,
        )

        # Fetch config from GitHub
        config = fetch_llm_recommendations_from_github()

        if not config:
            task_logger.warning("Failed to fetch GitHub config")
            return None

        # Sync to database
        with get_session_with_current_tenant() as db_session:
            results = sync_llm_models_from_github(db_session, config)

            if results:
                task_logger.info(f"Auto mode sync results: {results}")
            else:
                task_logger.debug("No model updates applied")

    except Exception:
        task_logger.exception("Error in auto LLM update task")
        raise

    return True
