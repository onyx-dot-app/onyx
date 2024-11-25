import time

from sqlalchemy.orm import Session

from danswer.chat.load_yamls import load_chat_yamls
from danswer.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from danswer.configs.app_configs import MANAGED_VESPA
from danswer.configs.constants import KV_REINDEX_KEY
from danswer.configs.constants import KV_SEARCH_SETTINGS
from danswer.configs.model_configs import FAST_GEN_AI_MODEL_VERSION
from danswer.configs.model_configs import GEN_AI_API_KEY
from danswer.configs.model_configs import GEN_AI_MODEL_VERSION
from danswer.db.connector import check_connectors_exist
from danswer.db.connector import create_initial_default_connector
from danswer.db.connector_credential_pair import associate_default_cc_pair
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.connector_credential_pair import resync_cc_pair
from danswer.db.credentials import create_initial_public_credential
from danswer.db.document import check_docs_exist
from danswer.db.index_attempt import cancel_indexing_attempts_past_model
from danswer.db.index_attempt import expire_index_attempts
from danswer.db.llm import fetch_default_provider
from danswer.db.llm import update_default_provider
from danswer.db.llm import upsert_llm_provider
from danswer.db.persona import delete_old_default_personas
from danswer.db.search_settings import get_current_search_settings
from danswer.db.search_settings import get_secondary_search_settings
from danswer.db.search_settings import update_current_search_settings
from danswer.db.search_settings import update_secondary_search_settings
from danswer.db.swap_index import check_index_swap
from danswer.document_index.factory import get_default_document_index
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.vespa.index import VespaIndex
from danswer.indexing.models import IndexingSetting
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from danswer.natural_language_processing.search_nlp_models import warm_up_cross_encoder
from danswer.search.models import SavedSearchSettings
from danswer.search.retrieval.search_runner import download_nltk_data
from danswer.seeding.load_docs import seed_initial_documents
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from danswer.server.settings.store import load_settings
from danswer.server.settings.store import store_settings
from danswer.tools.built_in_tools import auto_add_search_tool_to_personas
from danswer.tools.built_in_tools import load_builtin_tools
from danswer.tools.built_in_tools import refresh_built_in_tools_cache
from danswer.utils.gpu_utils import gpu_status_request
from danswer.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SUPPORTED_EMBEDDING_MODELS
from shared_configs.model_server_models import SupportedEmbeddingModel


logger = setup_logger()


def setup_danswer(db_session: Session, tenant_id: str | None) -> None:
    """
    Setup Danswer for a particular tenant. In the Single Tenant case, it will set it up for the default schema
    on server startup. In the MT case, it will be called when the tenant is created.

    The Tenant Service calls the tenants/create endpoint which runs this.
    """
    check_index_swap(db_session=db_session)
    search_settings = get_current_search_settings(db_session)
    secondary_search_settings = get_secondary_search_settings(db_session)

    # Break bad state for thrashing indexes
    if secondary_search_settings and DISABLE_INDEX_UPDATE_ON_SWAP:
        expire_index_attempts(
            search_settings_id=search_settings.id, db_session=db_session
        )

        for cc_pair in get_connector_credential_pairs(db_session):
            resync_cc_pair(cc_pair, db_session=db_session)

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
        warm_up_cross_encoder(search_settings.rerank_model_name)

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
        primary_index_name=search_settings.index_name,
        secondary_index_name=secondary_search_settings.index_name
        if secondary_search_settings
        else None,
    )

    success = setup_vespa(
        document_index,
        IndexingSetting.from_db_model(search_settings),
        IndexingSetting.from_db_model(secondary_search_settings)
        if secondary_search_settings
        else None,
    )
    if not success:
        raise RuntimeError("Could not connect to Vespa within the specified timeout.")

    logger.notice(f"Model Server: http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
    if search_settings.provider_type is None:
        warm_up_bi_encoder(
            embedding_model=EmbeddingModel.from_db_model(
                search_settings=search_settings,
                server_host=MODEL_SERVER_HOST,
                server_port=MODEL_SERVER_PORT,
            ),
        )

    # update multipass indexing setting based on GPU availability
    update_default_multipass_indexing(db_session)

    seed_initial_documents(db_session, tenant_id)


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
) -> bool:
    # Vespa startup is a bit slow, so give it a few seconds
    WAIT_SECONDS = 5
    VESPA_ATTEMPTS = 5
    for x in range(VESPA_ATTEMPTS):
        try:
            logger.notice(f"Setting up Vespa (attempt {x+1}/{VESPA_ATTEMPTS})...")
            document_index.ensure_indices_exist(
                index_embedding_dim=index_setting.model_dim,
                secondary_index_embedding_dim=secondary_index_setting.model_dim
                if secondary_index_setting
                else None,
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


def setup_postgres(db_session: Session) -> None:
    logger.notice("Verifying default connector/credential exist.")
    create_initial_public_credential(db_session)
    create_initial_default_connector(db_session)
    associate_default_cc_pair(db_session)

    logger.notice("Loading default Prompts and Personas")
    delete_old_default_personas(db_session)
    load_chat_yamls(db_session)

    logger.notice("Loading built-in tools")
    load_builtin_tools(db_session)
    refresh_built_in_tools_cache(db_session)
    auto_add_search_tool_to_personas(db_session)

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
            display_model_names=[llm_model, fast_model],
            model_names=[llm_model, fast_model],
        )
        new_llm_provider = upsert_llm_provider(
            llm_provider=model_req, db_session=db_session
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
        gpu_available = gpu_status_request()
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


def setup_multitenant_danswer() -> None:
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
