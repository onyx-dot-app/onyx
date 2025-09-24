from typing import cast
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.configs.app_configs import AZURE_DALLE_API_BASE
from onyx.configs.app_configs import AZURE_DALLE_API_KEY
from onyx.configs.app_configs import AZURE_DALLE_API_VERSION
from onyx.configs.app_configs import AZURE_DALLE_DEPLOYMENT_NAME
from onyx.configs.app_configs import IMAGE_MODEL_NAME
from onyx.configs.app_configs import OAUTH_CLIENT_ID
from onyx.configs.app_configs import OAUTH_CLIENT_SECRET
from onyx.configs.app_configs import OKTA_API_TOKEN
from onyx.configs.app_configs import OPENID_CONFIG_URL
from onyx.configs.constants import TMP_DRALPHA_PERSONA_NAME
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.mcp import get_all_mcp_tools_for_server
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.mcp import get_user_connection_config
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.tools.utils import compute_all_tool_tokens
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.headers import header_dict_to_header_list
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SearchToolConfig(BaseModel):
    answer_style_config: AnswerStyleConfig = Field(
        default_factory=lambda: AnswerStyleConfig(citation_config=CitationConfig())
    )
    document_pruning_config: DocumentPruningConfig = Field(
        default_factory=DocumentPruningConfig
    )
    retrieval_options: RetrievalDetails = Field(default_factory=RetrievalDetails)
    rerank_settings: RerankingDetails | None = None
    selected_sections: list[InferenceSection] | None = None
    chunks_above: int = 0
    chunks_below: int = 0
    full_doc: bool = False
    latest_query_files: list[InMemoryChatFile] | None = None
    # Use with care, should only be used for OnyxBot in channels with multiple users
    bypass_acl: bool = False


class WebSearchToolConfig(BaseModel):
    answer_style_config: AnswerStyleConfig = Field(
        default_factory=lambda: AnswerStyleConfig(
            citation_config=CitationConfig(all_docs_useful=True)
        )
    )
    document_pruning_config: DocumentPruningConfig = Field(
        default_factory=DocumentPruningConfig
    )


class ImageGenerationToolConfig(BaseModel):
    additional_headers: dict[str, str] | None = None


class CustomToolConfig(BaseModel):
    chat_session_id: UUID | None = None
    message_id: int | None = None
    additional_headers: dict[str, str] | None = None


def _get_image_generation_config(llm: LLM, db_session: Session) -> LLMConfig:
    """Helper function to get image generation LLM config based on available providers"""
    if llm and llm.config.api_key and llm.config.model_provider == "openai":
        return LLMConfig(
            model_provider=llm.config.model_provider,
            model_name=IMAGE_MODEL_NAME,
            temperature=GEN_AI_TEMPERATURE,
            api_key=llm.config.api_key,
            api_base=llm.config.api_base,
            api_version=llm.config.api_version,
            max_input_tokens=llm.config.max_input_tokens,
        )

    if llm.config.model_provider == "azure" and AZURE_DALLE_API_KEY is not None:
        return LLMConfig(
            model_provider="azure",
            model_name=f"azure/{AZURE_DALLE_DEPLOYMENT_NAME}",
            temperature=GEN_AI_TEMPERATURE,
            api_key=AZURE_DALLE_API_KEY,
            api_base=AZURE_DALLE_API_BASE,
            api_version=AZURE_DALLE_API_VERSION,
            max_input_tokens=llm.config.max_input_tokens,
        )

    # Fallback to checking for OpenAI provider in database
    llm_providers = fetch_existing_llm_providers(db_session)
    openai_provider = next(
        iter(
            [
                llm_provider
                for llm_provider in llm_providers
                if llm_provider.provider == "openai"
            ]
        ),
        None,
    )

    if not openai_provider or not openai_provider.api_key:
        raise ValueError("Image generation tool requires an OpenAI API key")

    return LLMConfig(
        model_provider=openai_provider.provider,
        model_name=IMAGE_MODEL_NAME,
        temperature=GEN_AI_TEMPERATURE,
        api_key=openai_provider.api_key,
        api_base=openai_provider.api_base,
        api_version=openai_provider.api_version,
        max_input_tokens=llm.config.max_input_tokens,
    )


# Note: this is not very clear / not the way things should generally be done. (+impure function)
# TODO: refactor the tool config flow to be easier
def _configure_document_pruning_for_tool_config(
    tool_config: SearchToolConfig | WebSearchToolConfig,
    tools: list[Tool],
    llm: LLM,
) -> None:
    """Helper function to configure document pruning settings for tool configs"""
    tool_config.document_pruning_config.tool_num_tokens = compute_all_tool_tokens(
        tools,
        get_tokenizer(
            model_name=llm.config.model_name,
            provider_type=llm.config.model_provider,
        ),
    )
    tool_config.document_pruning_config.using_tool_message = (
        explicit_tool_calling_supported(
            llm.config.model_provider, llm.config.model_name
        )
    )


def construct_tools(
    persona: Persona,
    prompt_config: PromptConfig,
    db_session: Session,
    user: User | None,
    llm: LLM,
    fast_llm: LLM,
    run_search_setting: OptionalSearchSetting,
    search_tool_config: SearchToolConfig | None = None,
    internet_search_tool_config: WebSearchToolConfig | None = None,
    image_generation_tool_config: ImageGenerationToolConfig | None = None,
    custom_tool_config: CustomToolConfig | None = None,
    allowed_tool_ids: list[int] | None = None,
    slack_context: SlackContext | None = None,
) -> dict[int, list[Tool]]:
    """Constructs tools based on persona configuration and available APIs.

    Will simply skip tools that are not allowed/available."""
    tool_dict: dict[int, list[Tool]] = {}

    mcp_tool_cache: dict[int, dict[int, MCPTool]] = {}
    # Get user's OAuth token if available
    user_oauth_token = None
    if user and user.oauth_accounts:
        user_oauth_token = user.oauth_accounts[0].access_token

    for db_tool_model in persona.tools:
        # If allowed_tool_ids is specified, skip tools not in the allowed list
        if allowed_tool_ids is not None and db_tool_model.id not in allowed_tool_ids:
            continue

        if db_tool_model.in_code_tool_id:
            tool_cls = get_built_in_tool_by_id(db_tool_model.in_code_tool_id)

            try:
                tool_is_available = tool_cls.is_available(db_session)
            except Exception:
                logger.exception(
                    "Failed checking availability for tool %s", tool_cls.__name__
                )
                tool_is_available = False

            if not tool_is_available:
                logger.debug(
                    "Skipping tool %s because it is not available",
                    tool_cls.__name__,
                )
                continue

            # Handle Search Tool
            if (
                tool_cls.__name__ == SearchTool.__name__
                and run_search_setting != OptionalSearchSetting.NEVER
            ):
                if not search_tool_config:
                    search_tool_config = SearchToolConfig()

                search_tool = SearchTool(
                    tool_id=db_tool_model.id,
                    db_session=db_session,
                    user=user,
                    persona=persona,
                    retrieval_options=search_tool_config.retrieval_options,
                    prompt_config=prompt_config,
                    llm=llm,
                    fast_llm=fast_llm,
                    document_pruning_config=search_tool_config.document_pruning_config,
                    answer_style_config=search_tool_config.answer_style_config,
                    selected_sections=search_tool_config.selected_sections,
                    chunks_above=search_tool_config.chunks_above,
                    chunks_below=search_tool_config.chunks_below,
                    full_doc=search_tool_config.full_doc,
                    evaluation_type=(
                        LLMEvaluationType.BASIC
                        if persona.llm_relevance_filter
                        else LLMEvaluationType.SKIP
                    ),
                    rerank_settings=search_tool_config.rerank_settings,
                    bypass_acl=search_tool_config.bypass_acl,
                    slack_context=slack_context,  # Pass the Slack context
                )
                tool_dict[db_tool_model.id] = [search_tool]

            # Handle Image Generation Tool
            elif tool_cls.__name__ == ImageGenerationTool.__name__:
                if not image_generation_tool_config:
                    image_generation_tool_config = ImageGenerationToolConfig()

                img_generation_llm_config = _get_image_generation_config(
                    llm, db_session
                )

                tool_dict[db_tool_model.id] = [
                    ImageGenerationTool(
                        api_key=cast(str, img_generation_llm_config.api_key),
                        api_base=img_generation_llm_config.api_base,
                        api_version=img_generation_llm_config.api_version,
                        additional_headers=image_generation_tool_config.additional_headers,
                        model=img_generation_llm_config.model_name,
                        tool_id=db_tool_model.id,
                    )
                ]

            # Handle Internet Search Tool
            elif tool_cls.__name__ == WebSearchTool.__name__:
                if not internet_search_tool_config:
                    internet_search_tool_config = WebSearchToolConfig()

                try:
                    tool_dict[db_tool_model.id] = [
                        WebSearchTool(tool_id=db_tool_model.id)
                    ]
                except ValueError as e:
                    logger.error(f"Failed to initialize Internet Search Tool: {e}")
                    raise ValueError(
                        "Internet search tool requires a search provider API key, please contact your Onyx admin to get it added!"
                    )
            # Handle Okta Profile Tool
            elif tool_cls.__name__ == OktaProfileTool.__name__:
                if not user_oauth_token:
                    raise ValueError(
                        "Okta Profile Tool requires user OAuth token but none found"
                    )

                if not all([OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OPENID_CONFIG_URL]):
                    raise ValueError(
                        "Okta Profile Tool requires OAuth configuration to be set"
                    )

                if not OKTA_API_TOKEN:
                    raise ValueError(
                        "Okta Profile Tool requires OKTA_API_TOKEN to be set"
                    )

                tool_dict[db_tool_model.id] = [
                    OktaProfileTool(
                        access_token=user_oauth_token,
                        client_id=OAUTH_CLIENT_ID,
                        client_secret=OAUTH_CLIENT_SECRET,
                        openid_config_url=OPENID_CONFIG_URL,
                        okta_api_token=OKTA_API_TOKEN,
                        tool_id=db_tool_model.id,
                    )
                ]

            # Handle KG Tool
            elif tool_cls.__name__ == KnowledgeGraphTool.__name__:

                # skip the knowledge graph tool if KG is not enabled/exposed
                kg_config = get_kg_config_settings()
                if not kg_config.KG_ENABLED or not kg_config.KG_EXPOSED:
                    logger.debug("Knowledge Graph Tool is not enabled/exposed")
                    continue

                if persona.name != TMP_DRALPHA_PERSONA_NAME:
                    # TODO: remove this after the beta period
                    raise ValueError(
                        f"The Knowledge Graph Tool should only be used by the '{TMP_DRALPHA_PERSONA_NAME}' Agent."
                    )
                tool_dict[db_tool_model.id] = [
                    KnowledgeGraphTool(tool_id=db_tool_model.id)
                ]

        # Handle custom tools
        elif db_tool_model.openapi_schema:
            if not custom_tool_config:
                custom_tool_config = CustomToolConfig()

            tool_dict[db_tool_model.id] = cast(
                list[Tool],
                build_custom_tools_from_openapi_schema_and_headers(
                    tool_id=db_tool_model.id,
                    openapi_schema=db_tool_model.openapi_schema,
                    dynamic_schema_info=DynamicSchemaInfo(
                        chat_session_id=custom_tool_config.chat_session_id,
                        message_id=custom_tool_config.message_id,
                    ),
                    custom_headers=(db_tool_model.custom_headers or [])
                    + (
                        header_dict_to_header_list(
                            custom_tool_config.additional_headers or {}
                        )
                    ),
                    user_oauth_token=(
                        user_oauth_token if db_tool_model.passthrough_auth else None
                    ),
                ),
            )

        # Handle MCP tools
        elif db_tool_model.mcp_server_id:
            if db_tool_model.mcp_server_id in mcp_tool_cache:
                tool_dict[db_tool_model.id] = [
                    mcp_tool_cache[db_tool_model.mcp_server_id][db_tool_model.id]
                ]
                continue

            mcp_server = get_mcp_server_by_id(db_tool_model.mcp_server_id, db_session)

            # Get user-specific connection config if needed
            connection_config = None
            user_email = user.email if user else ""

            if (
                mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
                or mcp_server.auth_type == MCPAuthenticationType.OAUTH
            ):
                # If server has a per-user template, only use that user's config
                if mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER:
                    connection_config = get_user_connection_config(
                        mcp_server.id, user_email, db_session
                    )
                else:
                    # No per-user template: use admin config
                    connection_config = mcp_server.admin_connection_config

            # Get all saved tools for this MCP server
            saved_tools = get_all_mcp_tools_for_server(mcp_server.id, db_session)

            # Find the specific tool that this database entry represents
            expected_tool_name = db_tool_model.display_name

            mcp_tool_cache[db_tool_model.mcp_server_id] = {}
            # Find the matching tool definition
            for saved_tool in saved_tools:
                # Create MCPTool instance for this specific tool
                mcp_tool = MCPTool(
                    tool_id=saved_tool.id,
                    mcp_server=mcp_server,
                    tool_name=saved_tool.name,
                    tool_description=saved_tool.description,
                    tool_definition=saved_tool.mcp_input_schema or {},
                    connection_config=connection_config,
                    user_email=user_email,
                )
                mcp_tool_cache[db_tool_model.mcp_server_id][saved_tool.id] = mcp_tool

                if saved_tool.id == db_tool_model.id:
                    tool_dict[saved_tool.id] = [cast(Tool, mcp_tool)]
            if db_tool_model.id not in tool_dict:
                logger.warning(
                    f"Tool '{expected_tool_name}' not found in MCP server '{mcp_server.name}'"
                )

    tools: list[Tool] = []
    for tool_list in tool_dict.values():
        tools.extend(tool_list)

    # factor in tool definition size when pruning
    if search_tool_config:
        _configure_document_pruning_for_tool_config(search_tool_config, tools, llm)

    if internet_search_tool_config:
        _configure_document_pruning_for_tool_config(
            internet_search_tool_config, tools, llm
        )

    return tool_dict
