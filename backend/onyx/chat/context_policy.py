from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from onyx.agents.runtime import AgentTurn
from onyx.chat.artifacts import ChatArtifacts
from onyx.chat.chat_state import PersonaPromptConfig
from onyx.chat.prompt_utils import (
    build_system_prompt,
    process_prompt_template,
    select_reminder_text,
)
from onyx.configs.model_configs import GEN_AI_INPUT_TOKEN_SAFETY_MARGIN
from onyx.context.messages import PromptMetadata, prompt_metadata
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLMInfo
from onyx.llm.models import (
    Message,
    SystemMessage,
    ToolChoiceOptions,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.utils import model_supports_image_input
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import PythonToolRichResponse
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.utils import compute_all_tool_tokens


class ChatReminderContext(BaseModel):
    ran_image_gen: bool
    has_open_url_tool: bool
    out_of_cycles: bool
    persona_task_prompt: str | None
    has_context_documents: bool


class ChatReminderPolicy:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._cite_documents = False
        self.just_ran_web_search = False
        self.file_generated = False

    @property
    def cite_documents(self) -> bool:
        return self.enabled and self._cite_documents

    def after_tools(self, responses: Sequence[ToolResultMessage]) -> None:
        self.just_ran_web_search = False
        if not self.enabled:
            return
        for response in responses:
            data = response.details
            if response.tool_name in CITEABLE_TOOLS_NAMES:
                self._cite_documents = True
            if isinstance(data, SearchDocsResponse):
                if data.search_docs and response.tool_name == WebSearchTool.NAME:
                    self.just_ran_web_search = True
            if (
                response.tool_name == PythonTool.NAME
                and isinstance(data, PythonToolRichResponse)
                and data.generated_files
            ):
                self.file_generated = True

    def render(self, context: ChatReminderContext) -> str | None:
        if not self.enabled:
            return context.persona_task_prompt
        return select_reminder_text(
            ran_image_gen=context.ran_image_gen,
            just_ran_web_search=self.just_ran_web_search,
            has_open_url_tool=context.has_open_url_tool,
            out_of_cycles=context.out_of_cycles,
            persona_task_prompt=context.persona_task_prompt,
            include_citation_reminder=self.cite_documents
            or context.has_context_documents,
            include_file_reminder=self.file_generated,
        )


class PreparedChatTurn(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    history: list[Message]
    tools: list[Tool]
    tool_choice: ToolChoiceOptions


class ChatContextPolicy:
    def __init__(
        self,
        *,
        tools: list[Tool],
        persona: PersonaPromptConfig | None,
        custom_prompt: str | None,
        base_prompt: str,
        files: ExtractedContextFiles,
        memory: UserMemoryContext | None,
        llm_info: LLMInfo,
        token_counter: Callable[[str], int],
        artifacts: ChatArtifacts,
        reminders: ChatReminderPolicy,
        forced_tool_id: int | None = None,
        file_metadata: dict[str, FileToolMetadata] | None = None,
        inject_memories: bool = True,
    ) -> None:
        self.tools = tools
        self.persona = persona
        self.files = files
        self.memory = memory
        self.llm_info = llm_info
        self.token_counter = token_counter
        self.artifacts = artifacts
        self.reminders = reminders
        self.forced_tool_id = forced_tool_id
        self.file_metadata = file_metadata
        self.inject_memories = inject_memories
        self.base_prompt = base_prompt
        values = memory.user_info.placeholder_values if memory else {}

        def substitute(text: str | None) -> str | None:
            return substitute_user_placeholders(text, values) if text else None

        self.custom_prompt = substitute(custom_prompt)
        self.persona_system = substitute(persona.system_prompt if persona else None)
        self.persona_task = substitute(persona.task_prompt if persona else None)

    def prepare(self, history: list[Message], turn: AgentTurn) -> PreparedChatTurn:
        tools = self.tools
        choice = ToolChoiceOptions.AUTO
        if self.forced_tool_id is not None:
            tools = [tool for tool in tools if tool.id == self.forced_tool_id]
            if not tools:
                raise ValueError(f"Tool {self.forced_tool_id} not found")
            self.forced_tool_id = None
            choice = ToolChoiceOptions.REQUIRED
        elif turn.is_last or self.artifacts.ran_image_gen:
            tools = []
            choice = ToolChoiceOptions.NONE

        context_documents = bool(
            self.files.use_as_search_filter or self.files.file_texts
        )
        cite = self.reminders.cite_documents or context_documents
        datetime_aware = self.persona.datetime_aware if self.persona else True

        def render(text: str | None, append_datetime: bool = False) -> str | None:
            return (
                process_prompt_template(
                    text,
                    datetime_aware=datetime_aware,
                    append_datetime_if_aware=append_datetime,
                    should_cite_documents=cite,
                )
                if text
                else None
            )

        custom = None
        if self.persona and self.persona.replace_base_system_prompt:
            system = render(self.persona_system, True)
        elif self.base_prompt:
            memory = (
                self.memory
                if self.inject_memories
                else self.memory.without_memories()
                if self.memory
                else None
            )
            system = build_system_prompt(
                base_system_prompt=self.base_prompt,
                datetime_aware=datetime_aware,
                user_memory_context=memory,
                tools=self.tools,
                should_cite_documents=cite,
            )
            custom = render(self.custom_prompt)
        else:
            system = render(self.custom_prompt, True)
        reminder = self.reminders.render(
            ChatReminderContext(
                ran_image_gen=self.artifacts.ran_image_gen,
                has_open_url_tool=any(
                    isinstance(tool, OpenURLTool) for tool in self.tools
                ),
                out_of_cycles=turn.is_last,
                persona_task_prompt=render(self.persona_task),
                has_context_documents=context_documents,
            )
        )
        image_markers = any(
            isinstance(message, UserMessage) and prompt_metadata(message).image_files
            for message in history
        ) and not model_supports_image_input(
            self.llm_info.model_name,
            self.llm_info.model_provider,
            self.llm_info.deployment_name,
        )
        budget = int(
            self.llm_info.max_input_tokens * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN)
        )
        prepared = prepare_prompt(
            system_prompt=SystemMessage(content=system) if system else None,
            custom_agent_prompt=UserMessage(content=custom) if custom else None,
            messages=history,
            reminder_message=UserMessage(
                content=reminder, metadata=PromptMetadata(is_reminder=True)
            )
            if reminder
            else None,
            context_files=self.files,
            available_tokens=max(
                0, budget - compute_all_tool_tokens(tools, self.token_counter)
            ),
            token_counter=self.token_counter,
            all_injected_file_metadata=self.file_metadata,
            image_files_replayed_as_markers=image_markers,
        )
        return PreparedChatTurn(history=prepared, tools=tools, tool_choice=choice)
