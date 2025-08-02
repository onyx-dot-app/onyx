from celery import shared_task
from celery import Task
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from onyx.llm.llm_provider_options import curated_models


def _delete_deprecated_not_visible_models(
    db_session: Session,
    llm_provider: LLMProvider,
    model_configurations: list[ModelConfiguration],
) -> None:
    """
    Delete models that are marked as deprecated in curated_models and not visible.
    """
    models_to_delete = []
    for model_configuration in model_configurations:
        for curated_model in curated_models[llm_provider.provider]:
            if (
                curated_model["name"] == model_configuration.name
                and curated_model.get("deprecated", False)
                and not model_configuration.is_visible
            ):
                models_to_delete.append(model_configuration)
    if models_to_delete:
        model_ids_to_delete = [model.id for model in models_to_delete]
        deleted_count = (
            db_session.query(ModelConfiguration)
            .filter(ModelConfiguration.id.in_(model_ids_to_delete))
            .delete(synchronize_session=False)
        )
        task_logger.info(
            f"Deleted {deleted_count} models for provider {llm_provider.provider}"
        )


def _sync_model_configurations_with_curated_models(
    db_session: Session,
    llm_provider: LLMProvider,
    model_configurations: list[ModelConfiguration],
) -> None:
    """
    Sync model configurations with curated models.
    """
    for curated_model in curated_models[llm_provider.provider]:
        model_configuration = (
            db_session.query(ModelConfiguration)
            .filter(
                ModelConfiguration.llm_provider_id == llm_provider.id,
                ModelConfiguration.name == curated_model["name"],
            )
            .first()
        )
        if model_configuration and (
            (
                model_configuration.recommended_default
                != curated_model["recommended_default_model"]
            )
            or (
                model_configuration.recommended_fast_default
                != curated_model["recommended_fast_default_model"]
            )
            or (
                model_configuration.recommended_is_visible
                != curated_model["recommended_is_visible"]
            )
        ):
            db_session.query(ModelConfiguration).filter(
                ModelConfiguration.id == model_configuration.id
            ).update(
                {
                    ModelConfiguration.recommended_default: curated_model[
                        "recommended_default_model"
                    ],
                    ModelConfiguration.recommended_fast_default: curated_model[
                        "recommended_fast_default_model"
                    ],
                    ModelConfiguration.recommended_is_visible: curated_model[
                        "recommended_is_visible"
                    ],
                }
            )
            task_logger.info(
                f"Updated model configuration for {curated_model['name']} for provider {llm_provider.provider}"
            )
        elif not model_configuration and not curated_model.get("deprecated", False):
            db_session.add(
                ModelConfiguration(
                    llm_provider_id=llm_provider.id,
                    name=curated_model["name"],
                    is_visible=curated_model["recommended_is_visible"],
                    recommended_default=curated_model["recommended_default_model"],
                    recommended_fast_default=curated_model[
                        "recommended_fast_default_model"
                    ],
                )
            )
            task_logger.info(
                f"Added model configuration for {curated_model['name']} for provider {llm_provider.provider}"
            )


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_LLM_MODEL_UPDATE_ONYX_CURATED,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_llm_model_update_onyx_curated(
    self: Task, *, tenant_id: str
) -> bool | None:
    """
    Check for LLM model updates using Onyx's curated model list.
    This task is used when LLM_MODEL_UPDATE_API_URL is not configured.
    """
    task_logger.info("Starting Onyx curated LLM model update check")

    try:
        with get_session_with_current_tenant() as db_session:
            llm_providers = db_session.query(LLMProvider).all()
            for llm_provider in llm_providers:
                if llm_provider.provider not in curated_models:
                    continue
                model_configurations = (
                    db_session.query(ModelConfiguration)
                    .filter(ModelConfiguration.llm_provider_id == llm_provider.id)
                    .all()
                )
                # Check if any model configuration is not in curated_models (custom provider)
                curated_model_names = [
                    model["name"] for model in curated_models[llm_provider.provider]
                ]
                has_custom_models = any(
                    mc.name not in curated_model_names for mc in model_configurations
                )
                if has_custom_models:
                    # Skip this provider iteration if any model is custom
                    continue
                _delete_deprecated_not_visible_models(
                    db_session, llm_provider, model_configurations
                )
                _sync_model_configurations_with_curated_models(
                    db_session, llm_provider, model_configurations
                )
                db_session.commit()
            task_logger.info(
                "Onyx curated LLM model update check completed successfully"
            )
            return True

    except Exception:
        task_logger.exception("Failed to update models using Onyx curated list")
        return None
