"""Serializable Onyx capabilities and immutable inputs for one model run."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from onyx.chat.chat_state import AvailableFiles, ChatStateContainer, ChatTurnSetup
from onyx.chat.emitter import Emitter
from onyx.chat.models import FileToolMetadata, SearchParams
from onyx.chat.pi.chat import ChatHost
from onyx.chat.pi.host_state import (
    ChatFileSnapshot,
    ChatMessageSnapshot,
    ContextFilesSnapshot,
)
from onyx.chat.prompt_utils import get_default_base_system_prompt
from onyx.db.agent_runs import load_host_records
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IncognitoRecordMode
from onyx.db.memory import UserMemoryContext
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLMConfig, LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import SendMessageRequest
from shared_configs.contextvars import (
    UsageCredentialIdentity,
    get_current_usage_credential,
)


class RunInputs(BaseModel):
    request: SendMessageRequest
    session_id: UUID
    user_id: UUID
    user_message_id: int
    user_identity: LLMUserIdentity
    usage_credential: UsageCredentialIdentity | None = None
    model: LLMConfig
    options: dict[str, Any]
    history: list[ChatMessageSnapshot]
    context_files: ContextFilesSnapshot
    reasoning_effort: ReasoningEffort
    search_params: SearchParams
    file_metadata: dict[str, FileToolMetadata]
    available_files: AvailableFiles
    forced_tool_id: int | None
    chat_files: list[ChatFileSnapshot]
    base_prompt: str
    system_prompt: str | None
    task_prompt: str | None
    replace_base_system_prompt: bool
    datetime_aware: bool
    custom_prompt: str | None
    memory: UserMemoryContext
    bypass_acl: bool
    slack_context: SlackContext | None
    tool_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None
    record_mode: IncognitoRecordMode | None
    reserved_tokens: int
    compression_window: int

    @classmethod
    def capture(
        cls, setup: ChatTurnSetup, user_id: UUID, model_index: int
    ) -> "RunInputs":
        llm = setup.llms[model_index]
        with get_session_with_current_tenant() as db_session:
            base_prompt = get_default_base_system_prompt(db_session)
        return cls(
            request=setup.new_msg_req,
            session_id=setup.chat_session_id,
            user_id=user_id,
            user_message_id=setup.user_message_id,
            user_identity=setup.user_identity,
            usage_credential=get_current_usage_credential(),
            model=llm.config,
            options=llm.request_options,
            history=[
                ChatMessageSnapshot.capture(message)
                for message in setup.simple_chat_history
            ],
            context_files=ContextFilesSnapshot.capture(setup.extracted_context_files),
            reasoning_effort=setup.reasoning_effort,
            search_params=setup.search_params,
            file_metadata=setup.all_injected_file_metadata,
            available_files=setup.available_files,
            forced_tool_id=setup.forced_tool_id,
            chat_files=[
                ChatFileSnapshot.capture(file) for file in setup.chat_files_for_tools
            ],
            base_prompt=base_prompt,
            system_prompt=setup.persona.system_prompt,
            task_prompt=setup.persona.task_prompt,
            replace_base_system_prompt=setup.persona.replace_base_system_prompt,
            datetime_aware=setup.persona.datetime_aware,
            custom_prompt=setup.custom_agent_prompt,
            memory=setup.user_memory_context,
            bypass_acl=setup.bypass_acl,
            slack_context=setup.slack_context,
            tool_headers=setup.custom_tool_additional_headers,
            mcp_headers=setup.mcp_headers,
            record_mode=setup.incognito_record_mode,
            reserved_tokens=setup.reserved_token_count,
            compression_window=min(llm.config.max_input_tokens for llm in setup.llms),
        )

    def build_host(self, emitter: Emitter) -> ChatHost:
        from onyx.chat.process_message import _should_enable_slack_search
        from onyx.server.settings.store import load_settings
        from onyx.tools.tool_constructor import (
            CustomToolConfig,
            FileReaderToolConfig,
            SearchToolConfig,
            construct_tools,
        )

        user, persona = load_host_records(self.session_id, self.user_id)
        llm = LitellmLLM(**self.model.model_dump(), model_kwargs=self.options)
        tool_dict = construct_tools(
            persona=persona,
            emitter=emitter,
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(
                user_selected_filters=self.request.internal_search_filters,
                project_id_filter=self.search_params.project_id_filter,
                persona_id_filter=self.search_params.persona_id_filter,
                bypass_acl=self.bypass_acl,
                slack_context=self.slack_context,
                enable_slack_search=_should_enable_slack_search(
                    persona, self.request.internal_search_filters
                ),
                auto_detect_filters=load_settings().auto_detect_search_filters
                is not False,
            ),
            custom_tool_config=CustomToolConfig(
                chat_session_id=self.session_id,
                message_id=self.user_message_id,
                additional_headers=self.tool_headers,
                mcp_headers=self.mcp_headers,
            ),
            file_reader_tool_config=FileReaderToolConfig(
                user_file_ids=self.available_files.user_file_ids,
                chat_file_ids=self.available_files.chat_file_ids,
            ),
            allowed_tool_ids=self.request.allowed_tool_ids,
            search_usage_forcing_setting=self.search_params.search_usage,
        )
        persona.system_prompt = self.system_prompt
        persona.task_prompt = self.task_prompt
        persona.replace_base_system_prompt = self.replace_base_system_prompt
        persona.datetime_aware = self.datetime_aware
        return ChatHost(
            emitter=emitter,
            state_container=ChatStateContainer(),
            simple_chat_history=[message.restore() for message in self.history],
            tools=[tool for tools in tool_dict.values() for tool in tools],
            custom_agent_prompt=self.custom_prompt,
            base_prompt=self.base_prompt,
            context_files=self.context_files.restore(),
            persona=persona,
            user_memory_context=self.memory,
            llm=llm,
            token_counter=get_llm_token_counter(llm),
            forced_tool_id=self.forced_tool_id,
            user_identity=self.user_identity,
            chat_session_id=str(self.session_id),
            chat_files=[file.restore() for file in self.chat_files],
            reasoning_effort=self.reasoning_effort,
            include_citations=self.request.include_citations,
            all_injected_file_metadata=self.file_metadata,
            inject_memories_in_prompt=user.use_memories,
        )
