"""Build application instructions independently of model calls and tool execution."""

from collections.abc import Callable

from onyx.chat.models import ChatMessageSimple
from onyx.chat.prompt_utils import build_system_prompt, process_prompt_template
from onyx.configs.constants import MessageType
from onyx.db.memory import UserMemoryContext
from onyx.db.models import Persona
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.tools.interface import Tool


class ChatInstructions:
    def __init__(
        self,
        *,
        base_prompt: str,
        custom_prompt: str | None,
        persona: Persona | None,
        memory: UserMemoryContext | None,
        include_memories: bool,
        tools: list[Tool],
        token_counter: Callable[[str], int],
    ) -> None:
        values = memory.user_info.placeholder_values if memory else {}
        self.base_prompt = base_prompt
        self.custom_prompt = (
            substitute_user_placeholders(custom_prompt, values)
            if custom_prompt
            else None
        )
        self.system_template = (
            substitute_user_placeholders(persona.system_prompt, values)
            if persona and persona.system_prompt
            else None
        )
        self.task_template = (
            substitute_user_placeholders(persona.task_prompt, values)
            if persona and persona.task_prompt
            else None
        )
        self.replace_base = bool(persona and persona.replace_base_system_prompt)
        self.datetime_aware = persona.datetime_aware if persona else True
        self.memory = (
            memory
            if include_memories
            else memory.without_memories()
            if memory
            else None
        )
        self.tools = tools
        self.token_counter = token_counter

    def render_template(
        self, template: str | None, cite: bool, *, append_datetime: bool
    ) -> str | None:
        if not template:
            return None
        return process_prompt_template(
            template,
            datetime_aware=self.datetime_aware,
            append_datetime_if_aware=append_datetime,
            should_cite_documents=cite,
        )

    def message(self, text: str | None, kind: MessageType) -> ChatMessageSimple | None:
        if not text:
            return None
        return ChatMessageSimple(
            message=text, token_count=self.token_counter(text), message_type=kind
        )

    def build(
        self, *, cite: bool
    ) -> tuple[ChatMessageSimple | None, ChatMessageSimple | None, str | None]:
        custom = None
        if self.replace_base:
            system = self.render_template(
                self.system_template, cite, append_datetime=True
            )
        elif self.base_prompt:
            system = build_system_prompt(
                base_system_prompt=self.base_prompt,
                datetime_aware=self.datetime_aware,
                user_memory_context=self.memory,
                tools=self.tools,
                should_cite_documents=cite,
            )
            custom = self.render_template(
                self.custom_prompt, cite, append_datetime=False
            )
        else:
            system = self.render_template(
                self.custom_prompt, cite, append_datetime=True
            )
        return (
            self.message(system, MessageType.SYSTEM),
            self.message(custom, MessageType.USER),
            self.render_template(self.task_template, cite, append_datetime=False),
        )
