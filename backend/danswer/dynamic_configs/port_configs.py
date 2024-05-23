import json
from pathlib import Path
from typing import cast

from danswer.configs.constants import GEN_AI_API_KEY_STORAGE_KEY
from danswer.configs.model_configs import FAST_GEN_AI_MODEL_VERSION
from danswer.configs.model_configs import GEN_AI_API_ENDPOINT
from danswer.configs.model_configs import GEN_AI_API_KEY
from danswer.configs.model_configs import GEN_AI_API_VERSION
from danswer.configs.model_configs import GEN_AI_MODEL_PROVIDER
from danswer.configs.model_configs import GEN_AI_MODEL_VERSION
from danswer.db.engine import get_session_context_manager
from danswer.db.llm import fetch_existing_llm_providers
from danswer.db.llm import update_default_provider
from danswer.db.llm import upsert_llm_provider
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.factory import PostgresBackedDynamicConfigStore
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from danswer.utils.logger import setup_logger


logger = setup_logger()


def read_file_system_store(directory_path: str) -> dict:
    store = {}
    base_path = Path(directory_path)
    for file_path in base_path.iterdir():
        if file_path.is_file() and "." not in file_path.name:
            with open(file_path, "r") as file:
                key = file_path.stem
                value = json.load(file)

                if value:
                    store[key] = value
    return store


def insert_into_postgres(store_data: dict) -> None:
    port_once_key = "file_store_ported"
    config_store = PostgresBackedDynamicConfigStore()
    try:
        config_store.load(port_once_key)
        return
    except ConfigNotFoundError:
        pass

    for key, value in store_data.items():
        config_store.store(key, value)

    config_store.store(port_once_key, True)


def port_filesystem_to_postgres(directory_path: str) -> None:
    store_data = read_file_system_store(directory_path)
    insert_into_postgres(store_data)


def port_api_key_to_postgres() -> None:
    # can't port over custom, no longer supported
    if GEN_AI_MODEL_PROVIDER == "custom":
        return

    with get_session_context_manager() as db_session:
        # if we already have ported things over / setup providers in the db, don't do anything
        if len(fetch_existing_llm_providers(db_session)) > 0:
            return

        api_key = GEN_AI_API_KEY
        try:
            api_key = cast(
                str, get_dynamic_config_store().load(GEN_AI_API_KEY_STORAGE_KEY)
            )
        except ConfigNotFoundError:
            pass

        # if no API key set, don't port anything over
        if not api_key:
            return

        default_model_name = GEN_AI_MODEL_VERSION
        if GEN_AI_MODEL_PROVIDER == "openai" and not default_model_name:
            default_model_name = "gpt-4"

        # if no default model name found, don't port anything over
        if not default_model_name:
            return

        default_fast_model_name = FAST_GEN_AI_MODEL_VERSION
        if GEN_AI_MODEL_PROVIDER == "openai" and not default_fast_model_name:
            default_fast_model_name = "gpt-3.5-turbo"

        llm_provider_upsert = LLMProviderUpsertRequest(
            name=GEN_AI_MODEL_PROVIDER,
            provider=GEN_AI_MODEL_PROVIDER,
            api_key=api_key,
            api_base=GEN_AI_API_ENDPOINT,
            api_version=GEN_AI_API_VERSION,
            # can't port over any custom configs, since we don't know
            # all the possible keys and values that could be in there
            custom_config=None,
            default_model_name=default_model_name,
            fast_default_model_name=default_fast_model_name,
            model_names=None,
        )
        llm_provider = upsert_llm_provider(db_session, llm_provider_upsert)
        update_default_provider(db_session, llm_provider.id)
        logger.info(f"Ported over LLM provider:\n\n{llm_provider}")

        # delete the old API key
        try:
            get_dynamic_config_store().delete(GEN_AI_API_KEY_STORAGE_KEY)
        except ConfigNotFoundError:
            pass
