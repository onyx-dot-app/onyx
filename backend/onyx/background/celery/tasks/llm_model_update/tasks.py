from typing import Any

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import OperationalError

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.cache.factory import get_shared_cache_backend
from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.configs.app_configs import AUTO_LLM_UPDATE_INTERVAL_SECONDS
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.auto_update_service import (
    fetch_llm_recommendations_from_github,
)
from onyx.llm.well_known_providers.auto_update_service import (
    get_cached_last_updated_at,
)
from onyx.llm.well_known_providers.auto_update_service import (
    set_cached_last_updated_at,
)
from onyx.llm.well_known_providers.auto_update_service import (
    sync_llm_models,
)
from onyx.llm.well_known_providers.auto_update_service import (
    sync_llm_models_from_github,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import IGNORED_SYNCING_TENANT_LIST


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_AUTO_LLM_UPDATE,
    ignore_result=True,
    soft_time_limit=300,  # 5 minute timeout
    autoretry_for=(OperationalError, OSError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    trail=False,
    bind=True,
)
def check_for_auto_llm_updates(
    self: Task,  # noqa: ARG001  # used implicitly by Celery autoretry_for
    *,
    tenant_id: str,  # noqa: ARG001
    llm_recommendations: dict[str, Any] | None = None,
    force: bool = False,
) -> bool | None:
    """Periodic task to fetch LLM model updates from GitHub
    and sync them to providers in Auto mode.

    This task checks the GitHub-hosted config file and updates all
    providers that have is_auto_mode=True.
    """
    if not AUTO_LLM_CONFIG_URL:
        task_logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping")
        return None

    try:
        # Sync to database
        with get_session_with_current_tenant() as db_session:
            if llm_recommendations is not None:
                results = sync_llm_models(
                    db_session=db_session,
                    config=LLMRecommendations.model_validate(llm_recommendations),
                    force=force,
                )
            else:
                results = sync_llm_models_from_github(db_session, force=force)

            if results:
                task_logger.info(f"Auto mode sync results: {results}")
            else:
                task_logger.debug("No model updates applied")

    except Exception:
        task_logger.exception("Error in auto LLM update task")
        raise

    return True


@shared_task(
    name=OnyxCeleryTask.CLOUD_CHECK_FOR_AUTO_LLM_UPDATE,
    ignore_result=True,
    soft_time_limit=15 * 60,
    time_limit=16 * 60,
    trail=False,
    bind=True,
)
def cloud_check_for_auto_llm_updates(
    self: Task,
) -> bool | None:
    if not AUTO_LLM_CONFIG_URL:
        task_logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping")
        return None

    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock = redis_client.lock(
        OnyxRedisLocks.CLOUD_CHECK_AUTO_LLM_UPDATE_LOCK,
        timeout=max(16 * 60, AUTO_LLM_UPDATE_INTERVAL_SECONDS),
    )

    if not lock.acquire(blocking=False):
        task_logger.debug("Auto LLM cloud update already running, skipping")
        return None

    release_lock = True
    try:
        llm_recommendations = fetch_llm_recommendations_from_github(raise_on_error=True)
        assert llm_recommendations is not None

        shared_cache = get_shared_cache_backend()
        last_updated_at = get_cached_last_updated_at(cache_backend=shared_cache)
        if last_updated_at and llm_recommendations.updated_at <= last_updated_at:
            set_cached_last_updated_at(
                last_updated_at,
                cache_backend=shared_cache,
            )
            task_logger.debug("GitHub config unchanged, skipping cloud fanout")
            return True

        serialized_recommendations = llm_recommendations.model_dump(mode="json")
        num_processed_tenants = 0

        for tenant_id in get_all_tenant_ids():
            if IGNORED_SYNCING_TENANT_LIST and tenant_id in IGNORED_SYNCING_TENANT_LIST:
                continue

            self.app.send_task(
                OnyxCeleryTask.CHECK_FOR_AUTO_LLM_UPDATE,
                kwargs={
                    "tenant_id": tenant_id,
                    "llm_recommendations": serialized_recommendations,
                    "force": True,
                },
                priority=OnyxCeleryPriority.LOW,
                expires=BEAT_EXPIRES_DEFAULT,
                ignore_result=True,
            )
            num_processed_tenants += 1

        set_cached_last_updated_at(
            llm_recommendations.updated_at,
            cache_backend=shared_cache,
        )
        task_logger.info(
            "Queued auto LLM updates for tenants: "
            f"updated_at={llm_recommendations.updated_at.isoformat()} "
            f"num_processed_tenants={num_processed_tenants}"
        )
    except SoftTimeLimitExceeded:
        release_lock = False
        task_logger.info(
            "Soft time limit exceeded in cloud auto LLM update task; "
            "leaving lock in place until timeout."
        )
        raise
    except Exception:
        task_logger.exception("Error in cloud auto LLM update task")
        raise
    finally:
        if release_lock and lock.owned():
            lock.release()

    return True
