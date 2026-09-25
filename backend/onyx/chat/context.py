from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from onyx.chat.llm_step import PromptMetadata
from onyx.chat.models import PersonaPromptConfig
from onyx.chat.prompt_utils import (
    build_system_prompt,
    process_prompt_template,
    select_reminder_text,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.models import (
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import LlmPythonExecutionResult
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


class ChatReminderContext(BaseModel):
    ran_image_gen: bool
    has_open_url_tool: bool
    out_of_cycles: bool
    persona_task_prompt: str | None
    has_context_documents: bool


class ChatReminders:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def should_cite(self, results: Sequence[ToolResultMessage]) -> bool:
        return self.enabled and any(
            result.tool_name in CITEABLE_TOOLS_NAMES for result in results
        )

    def render(
        self,
        context: ChatReminderContext,
        results: Sequence[ToolResultMessage],
        previous_results: Sequence[ToolResultMessage],
    ) -> str | None:
        if not self.enabled:
            return context.persona_task_prompt
        return select_reminder_text(
            ran_image_gen=context.ran_image_gen,
            just_ran_web_search=any(
                result.tool_name == WebSearchTool.NAME
                and isinstance(result.details, SearchDocsResponse)
                and result.details.search_docs
                for result in previous_results
            ),
            has_open_url_tool=context.has_open_url_tool,
            out_of_cycles=context.out_of_cycles,
            persona_task_prompt=context.persona_task_prompt,
            include_citation_reminder=self.should_cite(results)
            or context.has_context_documents,
            include_file_reminder=any(
                result.tool_name == PythonTool.NAME
                and isinstance(result.details, LlmPythonExecutionResult)
                and result.details.generated_files
                for result in results
            ),
        )


class ChatPrompt(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    system_prompt: Message | None
    custom_prompt: Message | None
    reminder: Message | None


class ChatContext:
    def __init__(
        self,
        *,
        tools: list[Tool],
        persona: PersonaPromptConfig | None,
        custom_prompt: str | None,
        base_prompt: str,
        files: ExtractedContextFiles,
        memory: UserMemoryContext | None,
        reminders: ChatReminders,
        inject_memories: bool = True,
    ) -> None:
        self.tools = tools
        self.persona = persona
        self.files = files
        self.memory = memory
        self.reminders = reminders
        self.inject_memories = inject_memories
        self.base_prompt = base_prompt
        values = memory.user_info.placeholder_values if memory else {}

        def substitute(text: str | None) -> str | None:
            return substitute_user_placeholders(text, values) if text else None

        self.custom_prompt = substitute(custom_prompt)
        self.persona_system = substitute(persona.system_prompt if persona else None)
        self.persona_task = substitute(persona.task_prompt if persona else None)

    def prepare(
        self,
        results: Sequence[ToolResultMessage],
        previous_results: Sequence[ToolResultMessage],
        *,
        is_last_step: bool,
        ran_image_gen: bool,
    ) -> ChatPrompt:
        context_documents = bool(
            self.files.use_as_search_filter or self.files.file_texts
        )
        cite = self.reminders.should_cite(results) or context_documents
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
                ran_image_gen=ran_image_gen,
                has_open_url_tool=any(
                    isinstance(tool, OpenURLTool) for tool in self.tools
                ),
                out_of_cycles=is_last_step,
                persona_task_prompt=render(self.persona_task),
                has_context_documents=context_documents,
            ),
            results,
            previous_results,
        )
        return ChatPrompt(
            system_prompt=SystemMessage(content=system) if system else None,
            custom_prompt=UserMessage(content=custom) if custom else None,
            reminder=UserMessage(
                content=reminder, metadata=PromptMetadata(is_reminder=True)
            )
            if reminder
            else None,
        )
