from typing import Any

import requests
from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import LLM_MODEL_UPDATE_API_URL
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration


def _process_model_list_response(model_list_json: Any) -> list[str]:
    # Handle case where response is wrapped in a "data" field
    if isinstance(model_list_json, dict):
        if "data" in model_list_json:
            model_list_json = model_list_json["data"]
        elif "models" in model_list_json:
            model_list_json = model_list_json["models"]
        else:
            raise ValueError(
                "Invalid response from API - expected dict with 'data' or "
                f"'models' field, got {type(model_list_json)}"
            )

    if not isinstance(model_list_json, list):
        raise ValueError(
            f"Invalid response from API - expected list, got {type(model_list_json)}"
        )

    # Handle both string list and object list cases
    model_names: list[str] = []
    for item in model_list_json:
        if isinstance(item, str):
            model_names.append(item)
        elif isinstance(item, dict):
            if "model_name" in item:
                model_names.append(item["model_name"])
            elif "id" in item:
                model_names.append(item["id"])
            else:
                raise ValueError(
                    f"Invalid item in model list - expected dict with model_name or id, got {type(item)}"
                )
        else:
            raise ValueError(
                f"Invalid item in model list - expected string or dict, got {type(item)}"
            )

    return model_names


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_LLM_MODEL_UPDATE,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_llm_model_update(self: Task, *, tenant_id: str) -> bool | None:
    if not LLM_MODEL_UPDATE_API_URL:
        raise ValueError("LLM model update API URL not configured")

    # First fetch the models from the API
    try:
        response = requests.get(LLM_MODEL_UPDATE_API_URL)
        response.raise_for_status()
        available_models = _process_model_list_response(response.json())
        task_logger.info(f"Found available models: {available_models}")

    except Exception:
        task_logger.exception("Failed to fetch models from API.")
        return None

    # Then update the database with the fetched models
    with get_session_with_current_tenant() as db_session:
        # Get the default LLM provider
        default_provider = (
            db_session.query(LLMProvider)
            .filter(LLMProvider.is_default_provider.is_(True))
            .first()
        )

        if not default_provider:
            task_logger.warning("No default LLM provider found")
            return None

        # log change if any
        old_models = set(
            model_configuration.name
            for model_configuration in default_provider.model_configurations
        )
        new_models = set(available_models)
        added_models = new_models - old_models
        removed_models = old_models - new_models

        if added_models:
            task_logger.info(f"Adding models: {sorted(added_models)}")
        if removed_models:
            task_logger.info(f"Removing models: {sorted(removed_models)}")

        # Update the provider's model list
        # Remove models that are no longer available
        db_session.query(ModelConfiguration).filter(
            ModelConfiguration.llm_provider_id == default_provider.id,
            ModelConfiguration.name.notin_(available_models),
        ).delete(synchronize_session=False)

        # Add new models
        for available_model_name in available_models:
            db_session.merge(
                ModelConfiguration(
                    llm_provider_id=default_provider.id,
                    name=available_model_name,
                    is_visible=False,
                    max_input_tokens=None,
                )
            )

        # if the default model is no longer available, set it to the first model in the list
        if default_provider.default_model_name not in available_models:
            task_logger.info(
                f"Default model {default_provider.default_model_name} not "
                f"available, setting to first model in list: {available_models[0]}"
            )
            default_provider.default_model_name = available_models[0]
        if default_provider.fast_default_model_name not in available_models:
            task_logger.info(
                f"Fast default model {default_provider.fast_default_model_name} "
                f"not available, setting to first model in list: {available_models[0]}"
            )
            default_provider.fast_default_model_name = available_models[0]
        db_session.commit()

        if added_models or removed_models:
            task_logger.info("Updated model list for default provider.")

    return True
