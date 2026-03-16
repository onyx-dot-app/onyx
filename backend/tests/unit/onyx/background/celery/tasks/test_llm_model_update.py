from datetime import datetime
from datetime import UTC
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.background.celery.tasks.llm_model_update.tasks import (
    cloud_check_for_auto_llm_updates,
)
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations


def _build_redis_mock_with_lock() -> tuple[MagicMock, MagicMock]:
    redis_client = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.owned.return_value = True
    redis_client.lock.return_value = lock
    return redis_client, lock


def _build_llm_recommendations() -> LLMRecommendations:
    return LLMRecommendations.model_validate(
        {
            "version": "1",
            "updated_at": datetime(2026, 3, 16, 22, 0, tzinfo=UTC).isoformat(),
            "providers": {
                "openai": {
                    "default_model": {"name": "gpt-4.1"},
                    "additional_visible_models": [{"name": "gpt-4.1-mini"}],
                }
            },
        }
    )


@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_shared_cache_backend")
@patch("onyx.background.celery.tasks.llm_model_update.tasks.set_cached_last_updated_at")
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_cached_last_updated_at")
@patch(
    "onyx.background.celery.tasks.llm_model_update.tasks.fetch_llm_recommendations_from_github"
)
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_redis_client")
def test_cloud_check_for_auto_llm_updates_skips_fanout_when_config_unchanged(
    mock_get_redis_client: MagicMock,
    mock_fetch_recommendations: MagicMock,
    mock_get_cached_last_updated_at: MagicMock,
    mock_set_cached_last_updated_at: MagicMock,
    mock_get_shared_cache_backend: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    mock_get_redis_client.return_value = redis_client
    llm_recommendations = _build_llm_recommendations()
    shared_cache = MagicMock()
    mock_fetch_recommendations.return_value = llm_recommendations
    mock_get_cached_last_updated_at.return_value = llm_recommendations.updated_at
    mock_get_shared_cache_backend.return_value = shared_cache

    task_app = MagicMock()
    with patch.object(cloud_check_for_auto_llm_updates, "app", task_app):
        cloud_check_for_auto_llm_updates.run()

    task_app.send_task.assert_not_called()
    mock_set_cached_last_updated_at.assert_called_once_with(
        llm_recommendations.updated_at,
        cache_backend=shared_cache,
    )
    lock.release.assert_called_once()


@patch(
    "onyx.background.celery.tasks.llm_model_update.tasks.IGNORED_SYNCING_TENANT_LIST",
    [],
)
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_all_tenant_ids")
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_shared_cache_backend")
@patch("onyx.background.celery.tasks.llm_model_update.tasks.set_cached_last_updated_at")
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_cached_last_updated_at")
@patch(
    "onyx.background.celery.tasks.llm_model_update.tasks.fetch_llm_recommendations_from_github"
)
@patch("onyx.background.celery.tasks.llm_model_update.tasks.get_redis_client")
def test_cloud_check_for_auto_llm_updates_enqueues_tenant_updates_on_change(
    mock_get_redis_client: MagicMock,
    mock_fetch_recommendations: MagicMock,
    mock_get_cached_last_updated_at: MagicMock,
    mock_set_cached_last_updated_at: MagicMock,
    mock_get_shared_cache_backend: MagicMock,
    mock_get_all_tenant_ids: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    mock_get_redis_client.return_value = redis_client
    llm_recommendations = _build_llm_recommendations()
    serialized_recommendations = llm_recommendations.model_dump(mode="json")
    shared_cache = MagicMock()
    mock_fetch_recommendations.return_value = llm_recommendations
    mock_get_cached_last_updated_at.return_value = None
    mock_get_shared_cache_backend.return_value = shared_cache
    mock_get_all_tenant_ids.return_value = ["tenant_a", "tenant_b"]

    task_app = MagicMock()
    with patch.object(cloud_check_for_auto_llm_updates, "app", task_app):
        cloud_check_for_auto_llm_updates.run()

    assert task_app.send_task.call_count == 2
    task_app.send_task.assert_any_call(
        OnyxCeleryTask.CHECK_FOR_AUTO_LLM_UPDATE,
        kwargs={
            "tenant_id": "tenant_a",
            "llm_recommendations": serialized_recommendations,
            "force": True,
        },
        priority=OnyxCeleryPriority.LOW,
        ignore_result=True,
    )
    task_app.send_task.assert_any_call(
        OnyxCeleryTask.CHECK_FOR_AUTO_LLM_UPDATE,
        kwargs={
            "tenant_id": "tenant_b",
            "llm_recommendations": serialized_recommendations,
            "force": True,
        },
        priority=OnyxCeleryPriority.LOW,
        ignore_result=True,
    )
    mock_set_cached_last_updated_at.assert_called_once_with(
        llm_recommendations.updated_at,
        cache_backend=shared_cache,
    )
    lock.release.assert_called_once()
