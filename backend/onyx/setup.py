import time

from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_NUM_ATTEMPTS_ON_STARTUP
from onyx.configs.chat_configs import INPUT_PROMPT_YAML
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.configs.constants import KV_SEARCH_SETTINGS
from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS
from onyx.configs.embedding_configs import SupportedEmbeddingModel
from onyx.configs.model_configs import FAST_GEN_AI_MODEL_VERSION
from onyx.configs.model_configs import GEN_AI_API_KEY
from onyx.configs.model_configs import GEN_AI_MODEL_VERSION
from onyx.context.search.models import SavedSearchSettings
from onyx.context.search.retrieval.search_runner import (
    download_nltk_data,
)
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import create_initial_default_connector
from onyx.db.connector_credential_pair import associate_default_cc_pair
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import resync_cc_pair
from onyx.db.credentials import create_initial_public_credential
from onyx.db.document import check_docs_exist
from onyx.db.enums import EmbeddingPrecision
from onyx.db.index_attempt import cancel_indexing_attempts_past_model
from onyx.db.index_attempt import expire_index_attempts
from onyx.db.llm import fetch_default_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.search_settings import update_current_search_settings
from onyx.db.search_settings import update_secondary_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.vespa.index import VespaIndex
from onyx.indexing.models import IndexingSetting
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.llm.llm_provider_options import OPEN_AI_MODEL_NAMES
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from onyx.natural_language_processing.search_nlp_models import warm_up_cross_encoder
from onyx.seeding.load_yamls import load_input_prompts_from_yaml
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.settings.store import load_settings
from onyx.server.settings.store import store_settings
from onyx.utils.gpu_utils import gpu_status_request
from onyx.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT


logger = setup_logger()


def setup_onyx(
    db_session: Session, tenant_id: str, cohere_enabled: bool = False
) -> None:
    """
    Setup Onyx for a particular tenant. In the Single Tenant case, it will set it up for the default schema
    on server startup. In the MT case, it will be called when the tenant is created.

    The Tenant Service calls the tenants/create endpoint which runs this.
    """
    check_and_perform_index_swap(db_session=db_session)

    active_search_settings = get_active_search_settings(db_session)
    search_settings = active_search_settings.primary
    secondary_search_settings = active_search_settings.secondary

    # search_settings = get_current_search_settings(db_session)
    # multipass_config_1 = get_multipass_config(search_settings)

    # secondary_large_chunks_enabled: bool | None = None
    # secondary_search_settings = get_secondary_search_settings(db_session)
    # if secondary_search_settings:
    #     multipass_config_2 = get_multipass_config(secondary_search_settings)
    #     secondary_large_chunks_enabled = multipass_config_2.enable_large_chunks

    # Break bad state for thrashing indexes
    if secondary_search_settings and DISABLE_INDEX_UPDATE_ON_SWAP:
        expire_index_attempts(
            search_settings_id=search_settings.id, db_session=db_session
        )

        for cc_pair in get_connector_credential_pairs(db_session):
            resync_cc_pair(
                cc_pair=cc_pair,
                search_settings_id=search_settings.id,
                db_session=db_session,
            )

    # Expire all old embedding models indexing attempts, technically redundant
    cancel_indexing_attempts_past_model(db_session)

    logger.notice(f'Using Embedding model: "{search_settings.model_name}"')
    if search_settings.query_prefix or search_settings.passage_prefix:
        logger.notice(f'Query embedding prefix: "{search_settings.query_prefix}"')
        logger.notice(f'Passage embedding prefix: "{search_settings.passage_prefix}"')

    if search_settings:
        if not search_settings.disable_rerank_for_streaming:
            logger.notice("Reranking is enabled.")

        if search_settings.multilingual_expansion:
            logger.notice(
                f"Multilingual query expansion is enabled with {search_settings.multilingual_expansion}."
            )
    if (
        search_settings.rerank_model_name
        and not search_settings.provider_type
        and not search_settings.rerank_provider_type
    ):
        # In integration tests, do not block API startup on warm-up
        warm_up_cross_encoder(
            search_settings.rerank_model_name,
            non_blocking=INTEGRATION_TESTS_MODE,
        )

    logger.notice("Verifying query preprocessing (NLTK) data is downloaded")
    download_nltk_data()

    # setup Postgres with default credential, llm providers, etc.
    setup_postgres(db_session)

    translate_saved_search_settings(db_session)

    # Does the user need to trigger a reindexing to bring the document index
    # into a good state, marked in the kv store
    if not MULTI_TENANT:
        mark_reindex_flag(db_session)

    # Ensure Vespa is setup correctly, this step is relatively near the end because Vespa
    # takes a bit of time to start up
    logger.notice("Verifying Document Index(s) is/are available.")
    document_index = get_default_document_index(
        search_settings,
        secondary_search_settings,
    )

    success = setup_vespa(
        document_index,
        IndexingSetting.from_db_model(search_settings),
        (
            IndexingSetting.from_db_model(secondary_search_settings)
            if secondary_search_settings
            else None
        ),
    )
    if not success:
        raise RuntimeError("Could not connect to Vespa within the specified timeout.")

    logger.notice(f"Model Server: http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
    if search_settings.provider_type is None:
        # In integration tests, do not block API startup on warm-up
        warm_up_bi_encoder(
            embedding_model=EmbeddingModel.from_db_model(
                search_settings=search_settings,
                server_host=MODEL_SERVER_HOST,
                server_port=MODEL_SERVER_PORT,
            ),
            non_blocking=INTEGRATION_TESTS_MODE,
        )

    # update multipass indexing setting based on GPU availability
    update_default_multipass_indexing(db_session)


def translate_saved_search_settings(db_session: Session) -> None:
    kv_store = get_kv_store()

    try:
        search_settings_dict = kv_store.load(KV_SEARCH_SETTINGS)
        if isinstance(search_settings_dict, dict):
            # Update current search settings
            current_settings = get_current_search_settings(db_session)

            # Update non-preserved fields
            if current_settings:
                current_settings_dict = SavedSearchSettings.from_db_model(
                    current_settings
                ).dict()

                new_current_settings = SavedSearchSettings(
                    **{**current_settings_dict, **search_settings_dict}
                )
                update_current_search_settings(db_session, new_current_settings)

            # Update secondary search settings
            secondary_settings = get_secondary_search_settings(db_session)
            if secondary_settings:
                secondary_settings_dict = SavedSearchSettings.from_db_model(
                    secondary_settings
                ).dict()

                new_secondary_settings = SavedSearchSettings(
                    **{**secondary_settings_dict, **search_settings_dict}
                )
                update_secondary_search_settings(
                    db_session,
                    new_secondary_settings,
                )
            # Delete the KV store entry after successful update
            kv_store.delete(KV_SEARCH_SETTINGS)
            logger.notice("Search settings updated and KV store entry deleted.")
        else:
            logger.notice("KV store search settings is empty.")
    except KvKeyNotFoundError:
        logger.notice("No search config found in KV store.")


def mark_reindex_flag(db_session: Session) -> None:
    kv_store = get_kv_store()
    try:
        value = kv_store.load(KV_REINDEX_KEY)
        logger.debug(f"Re-indexing flag has value {value}")
        return
    except KvKeyNotFoundError:
        # Only need to update the flag if it hasn't been set
        pass

    # If their first deployment is after the changes, it will
    # enable this when the other changes go in, need to avoid
    # this being set to False, then the user indexes things on the old version
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    if docs_exist or connectors_exist:
        kv_store.store(KV_REINDEX_KEY, True)
    else:
        kv_store.store(KV_REINDEX_KEY, False)


def setup_vespa(
    document_index: DocumentIndex,
    index_setting: IndexingSetting,
    secondary_index_setting: IndexingSetting | None,
    num_attempts: int = VESPA_NUM_ATTEMPTS_ON_STARTUP,
) -> bool:
    # Vespa startup is a bit slow, so give it a few seconds
    WAIT_SECONDS = 5
    for x in range(num_attempts):
        try:
            logger.notice(f"Setting up Vespa (attempt {x+1}/{num_attempts})...")
            document_index.ensure_indices_exist(
                primary_embedding_dim=index_setting.final_embedding_dim,
                primary_embedding_precision=index_setting.embedding_precision,
                secondary_index_embedding_dim=(
                    secondary_index_setting.final_embedding_dim
                    if secondary_index_setting
                    else None
                ),
                secondary_index_embedding_precision=(
                    secondary_index_setting.embedding_precision
                    if secondary_index_setting
                    else None
                ),
            )

            logger.notice("Vespa setup complete.")
            return True
        except Exception:
            logger.exception(
                f"Vespa setup did not succeed. The Vespa service may not be ready yet. Retrying in {WAIT_SECONDS} seconds."
            )
            time.sleep(WAIT_SECONDS)

    logger.error(
        f"Vespa setup did not succeed. Attempt limit reached. ({num_attempts})"
    )
    return False


def setup_postgres(db_session: Session) -> None:
    logger.notice("Verifying default connector/credential exist.")
    create_initial_public_credential(db_session)
    create_initial_default_connector(db_session)
    associate_default_cc_pair(db_session)

    # Load input prompts and user folders from YAML
    logger.notice("Loading input prompts and user folders")
    load_input_prompts_from_yaml(db_session, INPUT_PROMPT_YAML)

    if GEN_AI_API_KEY and fetch_default_provider(db_session) is None:
        # Only for dev flows
        logger.notice("Setting up default OpenAI LLM for dev.")

        llm_model = GEN_AI_MODEL_VERSION or "gpt-4o-mini"
        fast_model = FAST_GEN_AI_MODEL_VERSION or "gpt-4o-mini"
        model_req = LLMProviderUpsertRequest(
            name="DevEnvPresetOpenAI",
            provider="openai",
            api_key=GEN_AI_API_KEY,
            api_base=None,
            api_version=None,
            custom_config=None,
            default_model_name=llm_model,
            fast_default_model_name=fast_model,
            is_public=True,
            groups=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(name=name, is_visible=True)
                for name in OPEN_AI_MODEL_NAMES
            ],
            api_key_changed=True,
        )
        new_llm_provider = upsert_llm_provider(
            llm_provider_upsert_request=model_req, db_session=db_session
        )
        update_default_provider(provider_id=new_llm_provider.id, db_session=db_session)


def update_default_multipass_indexing(db_session: Session) -> None:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    logger.debug(f"Docs exist: {docs_exist}, Connectors exist: {connectors_exist}")

    if not docs_exist and not connectors_exist:
        logger.info(
            "No existing docs or connectors found. Checking GPU availability for multipass indexing."
        )
        gpu_available = gpu_status_request(indexing=True)
        logger.info(f"GPU available: {gpu_available}")

        current_settings = get_current_search_settings(db_session)

        logger.notice(f"Updating multipass indexing setting to: {gpu_available}")
        updated_settings = SavedSearchSettings.from_db_model(current_settings)
        # Enable multipass indexing if GPU is available or if using a cloud provider
        updated_settings.multipass_indexing = (
            gpu_available or current_settings.cloud_provider is not None
        )
        update_current_search_settings(db_session, updated_settings)

        # Update settings with GPU availability
        settings = load_settings()
        settings.gpu_enabled = gpu_available
        store_settings(settings)
        logger.notice(f"Updated settings with GPU availability: {gpu_available}")

    else:
        logger.debug(
            "Existing docs or connectors found. Skipping multipass indexing update."
        )


def setup_multitenant_onyx() -> None:
    # For Managed Vespa, the schema is sent over via the Vespa Console manually.
    if not MANAGED_VESPA:
        setup_vespa_multitenant(SUPPORTED_EMBEDDING_MODELS)


def setup_vespa_multitenant(supported_indices: list[SupportedEmbeddingModel]) -> bool:
    # This is for local testing
    WAIT_SECONDS = 5
    VESPA_ATTEMPTS = 5
    for x in range(VESPA_ATTEMPTS):
        try:
            logger.notice(f"Setting up Vespa (attempt {x+1}/{VESPA_ATTEMPTS})...")
            VespaIndex.register_multitenant_indices(
                indices=[index.index_name for index in supported_indices]
                + [
                    f"{index.index_name}{ALT_INDEX_SUFFIX}"
                    for index in supported_indices
                ],
                embedding_dims=[index.dim for index in supported_indices]
                + [index.dim for index in supported_indices],
                # on the cloud, just use float for all indices, the option to change this
                # is not exposed to the user
                embedding_precisions=[
                    EmbeddingPrecision.FLOAT for _ in range(len(supported_indices) * 2)
                ],
            )

            logger.notice("Vespa setup complete.")
            return True
        except Exception:
            logger.notice(
                f"Vespa setup did not succeed. The Vespa service may not be ready yet. Retrying in {WAIT_SECONDS} seconds."
            )
            time.sleep(WAIT_SECONDS)

    logger.error(
        f"Vespa setup did not succeed. Attempt limit reached. ({VESPA_ATTEMPTS})"
    )
    return False
