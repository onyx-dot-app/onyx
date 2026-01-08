from typing import cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import OAuthTokenManager
from onyx.chat.emitter import Emitter
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.context.search.models import BaseFilters
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.mcp import get_all_mcp_tools_for_server
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.mcp import get_user_connection_config
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.oauth_config import get_oauth_config
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tools import get_builtin_tool
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.onyxbot.slack.models import SlackContext
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.interface import Tool
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.models import SearchToolUsage
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    OpenURLTool,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.headers import header_dict_to_header_list
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SearchToolConfig(BaseModel):
    user_selected_filters: BaseFilters | None = None
    project_id: int | None = None
    bypass_acl: bool = False
    additional_context: str | None = None
    slack_context: SlackContext | None = None


class CustomToolConfig(BaseModel):
    chat_session_id: UUID | None = None
    message_id: int | None = None
    additional_headers: dict[str, str] | None = None


def _get_image_generation_config(llm: LLM, db_session: Session) -> LLMConfig:
    """Get image generation LLM config from the default image generation configuration."""
    from onyx.db.image_generation import get_default_image_generation_config

    default_config = get_default_image_generation_config(db_session)
    if (
        not default_config
        or not default_config.model_configuration
        or not default_config.model_configuration.llm_provider
    ):
        raise ValueError("No default image generation configuration found")

    llm_provider = default_config.model_configuration.llm_provider

    # For Azure, format model name as azure/<deployment_name> for LiteLLM
    model_name = default_config.model_configuration.name
    if llm_provider.provider == "azure":
        deployment = llm_provider.deployment_name or model_name
        model_name = f"azure/{deployment}"

    return LLMConfig(
        model_provider=llm_provider.provider,
        model_name=model_name,
        temperature=GEN_AI_TEMPERATURE,
        api_key=llm_provider.api_key,
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        deployment_name=llm_provider.deployment_name,
        max_input_tokens=llm.config.max_input_tokens,
    )


def construct_tools(
    persona: Persona,
    db_session: Session,
    emitter: Emitter,
    user: User | None,
    llm: LLM,
    search_tool_config: SearchToolConfig | None = None,
    custom_tool_config: CustomToolConfig | None = None,
    allowed_tool_ids: list[int] | None = None,
    search_usage_forcing_setting: SearchToolUsage = SearchToolUsage.AUTO,
) -> dict[int, list[Tool]]:
    """Constructs tools based on persona configuration and available APIs.

    Will simply skip tools that are not allowed/available."""
    tool_dict: dict[int, list[Tool]] = {}

    # Log which tools are attached to the persona for debugging
    persona_tool_names = [t.name for t in persona.tools]
    logger.debug(
        f"Constructing tools for persona '{persona.name}' (id={persona.id}): {persona_tool_names}"
    )

    mcp_tool_cache: dict[int, dict[int, MCPTool]] = {}
    # Get user's OAuth token if available
    user_oauth_token = None
    if user and user.oauth_accounts:
        user_oauth_token = user.oauth_accounts[0].access_token

    document_index_cache: DocumentIndex | None = None
    search_settings_cache = None

    def _get_document_index() -> DocumentIndex:
        nonlocal document_index_cache, search_settings_cache
        if document_index_cache is None:
            if search_settings_cache is None:
                search_settings_cache = get_current_search_settings(db_session)
            document_index_cache = get_default_document_index(
                search_settings_cache, None
            )
        return document_index_cache

    added_search_tool = False
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

            # Handle Internal Search Tool
            if tool_cls.__name__ == SearchTool.__name__:
                added_search_tool = True
                if search_usage_forcing_setting == SearchToolUsage.DISABLED:
                    continue

                if not search_tool_config:
                    search_tool_config = SearchToolConfig()

                # TODO concerning passing the db_session here.
                search_tool = SearchTool(
                    tool_id=db_tool_model.id,
                    db_session=db_session,
                    emitter=emitter,
                    user=user,
                    persona=persona,
                    llm=llm,
                    document_index=_get_document_index(),
                    user_selected_filters=search_tool_config.user_selected_filters,
                    project_id=search_tool_config.project_id,
                    bypass_acl=search_tool_config.bypass_acl,
                    slack_context=search_tool_config.slack_context,
                )

                tool_dict[db_tool_model.id] = [search_tool]

            # Handle Image Generation Tool
            elif tool_cls.__name__ == ImageGenerationTool.__name__:
                img_generation_llm_config = _get_image_generation_config(
                    llm, db_session
                )

                tool_dict[db_tool_model.id] = [
                    ImageGenerationTool(
                        api_key=cast(str, img_generation_llm_config.api_key),
                        api_base=img_generation_llm_config.api_base,
                        api_version=img_generation_llm_config.api_version,
                        model=img_generation_llm_config.model_name,
                        tool_id=db_tool_model.id,
                        emitter=emitter,
                    )
                ]

            # Handle Web Search Tool
            elif tool_cls.__name__ == WebSearchTool.__name__:
                try:
                    tool_dict[db_tool_model.id] = [
                        WebSearchTool(tool_id=db_tool_model.id, emitter=emitter)
                    ]
                except ValueError as e:
                    logger.error(f"Failed to initialize Internet Search Tool: {e}")
                    raise ValueError(
                        "Internet search tool requires a search provider API key, please contact your Onyx admin to get it added!"
                    )

            # Handle Open URL Tool
            elif tool_cls.__name__ == OpenURLTool.__name__:
                try:
                    tool_dict[db_tool_model.id] = [
                        OpenURLTool(
                            tool_id=db_tool_model.id,
                            emitter=emitter,
                            document_index=_get_document_index(),
                            user=user,
                        )
                    ]
                except RuntimeError as e:
                    logger.error(f"Failed to initialize Open URL Tool: {e}")
                    raise ValueError(
                        "Open URL tool requires a web content provider, please contact your Onyx admin to get it configured!"
                    )

            # Handle Python/Code Interpreter Tool
            elif tool_cls.__name__ == PythonTool.__name__:
                tool_dict[db_tool_model.id] = [
                    PythonTool(tool_id=db_tool_model.id, emitter=emitter)
                ]

            # Handle KG Tool
            # TODO: disabling for now because it's broken in the refactor
            # elif tool_cls.__name__ == KnowledgeGraphTool.__name__:

            #     # skip the knowledge graph tool if KG is not enabled/exposed
            #     kg_config = get_kg_config_settings()
            #     if not kg_config.KG_ENABLED or not kg_config.KG_EXPOSED:
            #         logger.debug("Knowledge Graph Tool is not enabled/exposed")
            #         continue

            #     if persona.name != TMP_DRALPHA_PERSONA_NAME:
            #         # TODO: remove this after the beta period
            #         raise ValueError(
            #             f"The Knowledge Graph Tool should only be used by the '{TMP_DRALPHA_PERSONA_NAME}' Agent."
            #         )
            #     tool_dict[db_tool_model.id] = [
            #         KnowledgeGraphTool(tool_id=db_tool_model.id)
            #     ]

        # Handle custom tools
        elif db_tool_model.openapi_schema:
            if not custom_tool_config:
                custom_tool_config = CustomToolConfig()

            # Determine which OAuth token to use
            oauth_token_for_tool = None

            # Priority 1: OAuth config (per-tool OAuth)
            if db_tool_model.oauth_config_id and user:
                oauth_config = get_oauth_config(
                    db_tool_model.oauth_config_id, db_session
                )
                if oauth_config:
                    token_manager = OAuthTokenManager(oauth_config, user.id, db_session)
                    oauth_token_for_tool = token_manager.get_valid_access_token()
                    if not oauth_token_for_tool:
                        logger.warning(
                            f"No valid OAuth token found for tool {db_tool_model.id} "
                            f"with OAuth config {db_tool_model.oauth_config_id}"
                        )

            # Priority 2: Passthrough auth (user's login OAuth token)
            elif db_tool_model.passthrough_auth:
                oauth_token_for_tool = user_oauth_token

            tool_dict[db_tool_model.id] = cast(
                list[Tool],
                build_custom_tools_from_openapi_schema_and_headers(
                    tool_id=db_tool_model.id,
                    openapi_schema=db_tool_model.openapi_schema,
                    emitter=emitter,
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
                    user_oauth_token=oauth_token_for_tool,
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
            mcp_user_oauth_token = None

            if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
                # Pass-through OAuth: use the user's login OAuth token
                mcp_user_oauth_token = user_oauth_token
            elif (
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
                    emitter=emitter,
                    mcp_server=mcp_server,
                    tool_name=saved_tool.name,
                    tool_description=saved_tool.description,
                    tool_definition=saved_tool.mcp_input_schema or {},
                    connection_config=connection_config,
                    user_email=user_email,
                    user_oauth_token=mcp_user_oauth_token,
                )
                mcp_tool_cache[db_tool_model.mcp_server_id][saved_tool.id] = mcp_tool

                if saved_tool.id == db_tool_model.id:
                    tool_dict[saved_tool.id] = [cast(Tool, mcp_tool)]
            if db_tool_model.id not in tool_dict:
                logger.warning(
                    f"Tool '{expected_tool_name}' not found in MCP server '{mcp_server.name}'"
                )

    if (
        not added_search_tool
        and search_usage_forcing_setting == SearchToolUsage.ENABLED
    ):
        # Get the database tool model for SearchTool
        search_tool_db_model = get_builtin_tool(db_session, SearchTool)

        # Use the passed-in config if available, otherwise create a new one
        if not search_tool_config:
            search_tool_config = SearchToolConfig()

        search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(search_settings, None)

        search_tool = SearchTool(
            tool_id=search_tool_db_model.id,
            db_session=db_session,
            emitter=emitter,
            user=user,
            persona=persona,
            llm=llm,
            document_index=document_index,
            user_selected_filters=search_tool_config.user_selected_filters,
            project_id=search_tool_config.project_id,
            bypass_acl=search_tool_config.bypass_acl,
            slack_context=search_tool_config.slack_context,
        )

        tool_dict[search_tool_db_model.id] = [search_tool]

    tools: list[Tool] = []
    for tool_list in tool_dict.values():
        tools.extend(tool_list)

    return tool_dict
