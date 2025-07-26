from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration


@shared_task(
    name=OnyxCeleryTask.UPDATE_RECOMMENDED_SELECTED_MODELS,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def update_recommended_selected_models(self: Task, *, tenant_id: str) -> bool | None:
    """
    Update the recommended and selected status of LLM models based on configuration.
    This task manages which models should be recommended as default or fast default,
    and ensures proper visibility settings are applied.
    """
    task_logger.info("Starting recommended selected models update")

    try:
        with get_session_with_current_tenant() as db_session:
            llm_providers = db_session.query(LLMProvider).all()
            for llm_provider in llm_providers:
                if llm_provider.use_recommended_models:
                    model_configurations = (
                        db_session.query(ModelConfiguration)
                        .filter(ModelConfiguration.llm_provider_id == llm_provider.id)
                        .all()
                    )
                    for model_configuration in model_configurations:
                        if (
                            model_configuration.recommended_is_visible is not None
                            and model_configuration.is_visible
                            != model_configuration.recommended_is_visible
                        ):
                            db_session.query(ModelConfiguration).filter(
                                ModelConfiguration.id == model_configuration.id
                            ).update(
                                {
                                    ModelConfiguration.is_visible: model_configuration.recommended_is_visible
                                }
                            )
                            task_logger.info(
                                f"Updated is_visible for model {model_configuration.name} for provider {llm_provider.provider}"
                            )
                        if (
                            model_configuration.recommended_default
                            and model_configuration.name
                            != llm_provider.default_model_name
                        ):
                            db_session.query(LLMProvider).filter(
                                LLMProvider.id == llm_provider.id
                            ).update(
                                {
                                    LLMProvider.default_model_name: model_configuration.name
                                }
                            )
                            task_logger.info(
                                f"""
                                Updated default_model_name for model {model_configuration.name}
                                for provider {llm_provider.provider}
                                """
                            )
                        if (
                            model_configuration.recommended_fast_default
                            and model_configuration.name
                            != llm_provider.fast_default_model_name
                        ):
                            db_session.query(LLMProvider).filter(
                                LLMProvider.id == llm_provider.id
                            ).update(
                                {
                                    LLMProvider.fast_default_model_name: model_configuration.name
                                }
                            )
                            task_logger.info(
                                f"""
                                Updated fast_default_model_name for model {model_configuration.name}
                                for provider {llm_provider.provider}
                                """
                            )
                    db_session.commit()
            task_logger.info(
                "Recommended selected models update completed successfully"
            )
            return True

    except Exception:
        task_logger.exception("Failed to update recommended selected models")
        return None
