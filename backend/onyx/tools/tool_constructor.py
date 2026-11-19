from collections.abc import Callable, Sequence
from typing import cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.chat_configs import DISABLE_POSTGRES_QUERY_TOOL
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.context.search.models import BaseFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant_if_none
from onyx.db.image_generation import get_default_image_generation_config
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tools import get_builtin_tool
from onyx.document_index.factory import get_default_document_index
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.models import ApprovalMode
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.onyxbot.slack.models import SlackContext
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.interface import Tool
from onyx.tools.models import (
    IntegrationChatRequest,
    PersonaToolConfiguration,
    SearchToolUsage,
    ToolConfiguration,
    ToolOptions,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool
from onyx.tools.tool_implementations.postgres.scope import build_document_scope
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SearchToolConfig(BaseModel):
    user_selected_filters: BaseFilters | None = None
    # Document index metadata filters for overflowing user files.  These are NOT the
    # IDs of the current project/persona — they are only set when the
    # project's/persona's user files didn't fit in the LLM context window and
    # must be found via vector DB search instead.
    project_id_filter: int | None = None
    persona_id_filter: int | None = None
    additional_context: str | None = None
    slack_context: SlackContext | None = None
    enable_slack_search: bool = True
    auto_detect_filters: bool = True


class FileReaderToolConfig(BaseModel):
    # IDs from the ``user_file`` table (project / persona-attached files).
    user_file_ids: list[UUID] = []
    # IDs from the ``file_record`` table (chat-attached files).
    chat_file_ids: list[UUID] = []


class CustomToolConfig(BaseModel):
    chat_session_id: UUID | None = None
    message_id: int | None = None
    additional_headers: dict[str, str] | None = None
    mcp_headers: dict[str, str] | None = None


def _get_image_generation_config(llm: LLM, db_session: Session) -> LLMConfig:
    """Load the default image generation provider and credentials."""
    default_config = get_default_image_generation_config(db_session)
    if (
        not default_config
        or not default_config.model_configuration
        or not default_config.model_configuration.llm_provider
    ):
        raise ValueError("No default image generation configuration found")

    llm_provider = default_config.model_configuration.llm_provider

    return LLMConfig(
        model_provider=llm_provider.provider,
        model_name=default_config.model_configuration.name,
        temperature=GEN_AI_TEMPERATURE,
        api_key=(
            llm_provider.api_key.get_value(apply_mask=False)
            if llm_provider.api_key
            else None
        ),
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        # A linked provider's deployment serves its chat model, not this one.
        deployment_name=(
            llm_provider.deployment_name if default_config.llm_provider_owned else None
        ),
        max_input_tokens=llm.config.max_input_tokens,
        custom_config=llm_provider.custom_config,
    )


def _require_chat_session_id(
    custom_tool_config: CustomToolConfig | None, tool_name: str
) -> UUID:
    """Generated files are scoped to the chat session that produced them, so
    the tools that write them cannot be built without one."""
    if custom_tool_config is None or custom_tool_config.chat_session_id is None:
        raise ValueError(
            f"{tool_name} requires CustomToolConfig.chat_session_id: generated "
            "files are scoped to the chat session that produced them"
        )
    return custom_tool_config.chat_session_id


def should_disable_open_url_web_fetch(
    persona_tools: Sequence[ToolConfiguration],
    tool_options: ToolOptions | None,
) -> bool:
    """OpenURLTool is hidden from the chat tool toggles (chat_selectable=False)
    but reaches the live internet on its own via the crawler fallback. Treat an
    explicit exclusion of WebSearchTool as disabling OpenURLTool's web
    fetching, so that turning off web search for a message actually cuts off
    web access — while pasted links can still be served from indexed
    documents."""
    if tool_options is None:
        return False
    return any(
        tool.in_code_tool_id == WebSearchTool.__name__
        and not tool_options.allows_tool(tool.id)
        for tool in persona_tools
    )


def postgres_query_tool_for_turn(
    tools: list[Tool],
    user: User,
    configuration: PersonaToolConfiguration,
    search_tool_config: SearchToolConfig | None,
    custom_tool_config: CustomToolConfig | None,
) -> PostgresTool | None:
    """The postgres_query tool for a turn that has internal search, scoped to
    the same knowledge; None without search or when the deployment turns the
    tool off."""
    if DISABLE_POSTGRES_QUERY_TOOL or not any(
        isinstance(tool, SearchTool) for tool in tools
    ):
        return None
    return PostgresTool(
        user=user,
        current_chat_session_id=(
            custom_tool_config.chat_session_id if custom_tool_config else None
        ),
        scope=build_document_scope(
            persona_search=configuration.search,
            user_selected_filters=(
                search_tool_config.user_selected_filters if search_tool_config else None
            ),
            project_id_filter=(
                search_tool_config.project_id_filter if search_tool_config else None
            ),
            persona_id_filter=(
                search_tool_config.persona_id_filter if search_tool_config else None
            ),
        ),
    )


def construct_tools(
    configuration: PersonaToolConfiguration,
    user: User,
    llm: LLM,
    db_session: Session | None = None,
    search_tool_config: SearchToolConfig | None = None,
    custom_tool_config: CustomToolConfig | None = None,
    file_reader_tool_config: FileReaderToolConfig | None = None,
    tool_options: ToolOptions | None = None,
    search_usage_forcing_setting: SearchToolUsage = SearchToolUsage.AUTO,
    selection_llm_factory: Callable[[], LLM] | None = None,
    approval_mode: ApprovalMode = ApprovalMode.INTERACTIVE,
) -> list[Tool]:
    """Build the built-in tools from captured settings and the tools of the
    integrations the agent can use, with current credentials and policies.
    A Blocked action is never built; ``approval_mode`` decides what an Ask
    action does."""
    with get_session_with_current_tenant_if_none(db_session) as db_session:
        return _construct_tools_impl(
            configuration=configuration,
            db_session=db_session,
            user=user,
            llm=llm,
            selection_llm_factory=selection_llm_factory,
            search_tool_config=search_tool_config,
            custom_tool_config=custom_tool_config,
            file_reader_tool_config=file_reader_tool_config,
            tool_options=tool_options,
            search_usage_forcing_setting=search_usage_forcing_setting,
            approval_mode=approval_mode,
        )


def _construct_tools_impl(
    configuration: PersonaToolConfiguration,
    db_session: Session,
    user: User,
    llm: LLM,
    search_tool_config: SearchToolConfig | None = None,
    custom_tool_config: CustomToolConfig | None = None,
    file_reader_tool_config: FileReaderToolConfig | None = None,
    tool_options: ToolOptions | None = None,
    search_usage_forcing_setting: SearchToolUsage = SearchToolUsage.AUTO,
    selection_llm_factory: Callable[[], LLM] | None = None,
    approval_mode: ApprovalMode = ApprovalMode.INTERACTIVE,
) -> list[Tool]:
    tools: list[Tool] = []

    persona_tool_names = [t.name for t in configuration.tools]
    logger.debug(
        "Constructing tools for persona '%s' (id=%s): %s",
        configuration.persona_name,
        configuration.persona_id,
        persona_tool_names,
    )

    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    def _build_search_tool(tool_id: int, config: SearchToolConfig) -> SearchTool:
        return SearchTool(
            tool_id=tool_id,
            user=user,
            persona_search_info=configuration.search,
            llm=llm,
            selection_llm_factory=selection_llm_factory,
            document_index=document_index,
            user_selected_filters=config.user_selected_filters,
            project_id_filter=config.project_id_filter,
            persona_id_filter=config.persona_id_filter,
            slack_context=config.slack_context,
            enable_slack_search=config.enable_slack_search,
            auto_detect_filters=config.auto_detect_filters,
        )

    open_url_web_fetch_disabled = should_disable_open_url_web_fetch(
        configuration.tools, tool_options
    )

    added_search_tool = False
    for db_tool_model in configuration.tools:
        if not db_tool_model.enabled:
            continue

        if tool_options is not None and not tool_options.allows_tool(db_tool_model.id):
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

                tools.append(_build_search_tool(db_tool_model.id, search_tool_config))

            # Handle Image Generation Tool
            elif tool_cls.__name__ == ImageGenerationTool.__name__:
                img_generation_llm_config = _get_image_generation_config(
                    llm, db_session
                )

                tools.append(
                    ImageGenerationTool(
                        image_generation_credentials=ImageGenerationProviderCredentials(
                            api_key=cast(str, img_generation_llm_config.api_key),
                            api_base=img_generation_llm_config.api_base,
                            api_version=img_generation_llm_config.api_version,
                            deployment_name=(
                                img_generation_llm_config.deployment_name
                                or img_generation_llm_config.model_name
                            ),
                            custom_config=img_generation_llm_config.custom_config,
                        ),
                        provider=img_generation_llm_config.model_provider,
                        model=img_generation_llm_config.model_name,
                        tool_id=db_tool_model.id,
                        chat_session_id=_require_chat_session_id(
                            custom_tool_config, ImageGenerationTool.__name__
                        ),
                    )
                )

            # Handle Web Search Tool
            elif tool_cls.__name__ == WebSearchTool.__name__:
                try:
                    tools.append(WebSearchTool(tool_id=db_tool_model.id))
                except ValueError as e:
                    logger.error("Failed to initialize Internet Search Tool: %s", e)
                    raise ValueError(
                        "Internet search tool requires a search provider API key, please contact your Onyx admin to get it added!"
                    ) from e

            # Handle Open URL Tool
            elif tool_cls.__name__ == OpenURLTool.__name__:
                if open_url_web_fetch_disabled and DISABLE_VECTOR_DB:
                    # Without an index, open_url can serve nothing once web
                    # fetching is off (crawl-only deployments).
                    logger.debug(
                        "Skipping OpenURLTool: WebSearchTool is excluded for "
                        "this message and no document index is available"
                    )
                    continue
                try:
                    tools.append(
                        OpenURLTool(
                            tool_id=db_tool_model.id,
                            document_index=document_index,
                            user=user,
                            web_fetch_disabled=open_url_web_fetch_disabled,
                        )
                    )
                except RuntimeError as e:
                    logger.error("Failed to initialize Open URL Tool: %s", e)
                    raise ValueError(
                        "Open URL tool requires a web content provider, please contact your Onyx admin to get it configured!"
                    ) from e

            # Handle Python/Code Interpreter Tool
            elif tool_cls.__name__ == PythonTool.__name__:
                tools.append(
                    PythonTool(
                        tool_id=db_tool_model.id,
                        chat_session_id=_require_chat_session_id(
                            custom_tool_config, PythonTool.__name__
                        ),
                    )
                )

            # Handle File Reader Tool
            elif tool_cls.__name__ == FileReaderTool.__name__:
                cfg = file_reader_tool_config or FileReaderToolConfig()
                tools.append(
                    FileReaderTool(
                        tool_id=db_tool_model.id,
                        user_file_ids=cfg.user_file_ids,
                        chat_file_ids=cfg.chat_file_ids,
                    )
                )

    if (
        not added_search_tool
        and search_usage_forcing_setting == SearchToolUsage.ENABLED
        and not DISABLE_VECTOR_DB
    ):
        # Get the database tool model for SearchTool
        search_tool_db_model = get_builtin_tool(db_session, SearchTool)

        if not search_tool_config:
            search_tool_config = SearchToolConfig()

        tools.append(_build_search_tool(search_tool_db_model.id, search_tool_config))

    # Always inject MemoryTool when the user has the memory tool enabled,
    # bypassing persona tool associations and the tool options
    if user.enable_memory_tool:
        try:
            memory_tool_db_model = get_builtin_tool(db_session, MemoryTool)
            memory_tool = MemoryTool(
                tool_id=memory_tool_db_model.id,
                llm=llm,
            )
            tools.append(memory_tool)
        except RuntimeError:
            logger.warning(
                "MemoryTool not found in the database. Run the latest alembic migration to seed it."
            )

    postgres_tool = postgres_query_tool_for_turn(
        tools, user, configuration, search_tool_config, custom_tool_config
    )
    if postgres_tool is not None:
        tools.append(postgres_tool)

    custom_tool_config = custom_tool_config or CustomToolConfig()
    integration_tools = build_integration_chat_tools(
        db_session,
        user,
        IntegrationChatRequest(
            persona_id=configuration.persona_id,
            plugin_links=configuration.plugin_links,
            approval_mode=approval_mode,
            chat_session_id=custom_tool_config.chat_session_id,
            message_id=custom_tool_config.message_id,
            additional_headers=custom_tool_config.additional_headers or {},
            mcp_headers=custom_tool_config.mcp_headers,
            allowed_plugins=tool_options.allowed_plugins() if tool_options else None,
        ),
    )
    return tools + integration_tools
