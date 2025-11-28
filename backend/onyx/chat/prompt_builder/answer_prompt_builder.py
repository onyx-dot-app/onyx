from collections.abc import Callable
from collections.abc import Sequence
from typing import cast

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic.v1 import BaseModel as BaseModel__v1

from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.citations_prompt import compute_max_llm_input_tokens
from onyx.chat.prompt_builder.utils import translate_history_to_basemessages
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import build_content_with_imgs
from onyx.llm.utils import check_message_tokens
from onyx.llm.utils import message_to_prompt_and_imgs
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.llm.utils import model_supports_image_input
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.chat_prompts import CHAT_USER_CONTEXT_FREE_PROMPT
from onyx.prompts.chat_prompts import CODE_BLOCK_MARKDOWN
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT
from onyx.prompts.chat_prompts import LONG_CONVERSATION_REMINDER_PROMPT
from onyx.prompts.chat_prompts import TOOL_PERSISTENCE_PROMPT
from onyx.prompts.direct_qa_prompts import HISTORY_BLOCK
from onyx.prompts.prompt_utils import drop_messages_history_overflow
from onyx.prompts.prompt_utils import handle_company_awareness
from onyx.prompts.prompt_utils import handle_memories
from onyx.prompts.prompt_utils import handle_onyx_date_awareness
from onyx.tools.force import ForceUseTool
from onyx.tools.models import ToolCallFinalResult
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool


def default_build_system_message_v2(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    memories: list[str] | None = None,
    tools: Sequence[Tool] | None = None,
    should_cite_documents: bool = False,
) -> SystemMessage:
    system_prompt = (
        prompt_config.default_behavior_system_prompt or DEFAULT_SYSTEM_PROMPT
    )

    # See https://simonwillison.net/tags/markdown/ for context on why this is needed
    # for OpenAI reasoning models to have correct markdown generation
    if model_needs_formatting_reenabled(llm_config.model_name):
        system_prompt = CODE_BLOCK_MARKDOWN + system_prompt

    tag_handled_prompt = handle_onyx_date_awareness(
        system_prompt,
        prompt_config,
        add_additional_info_if_no_tag=prompt_config.datetime_aware,
    )

    tag_handled_prompt = handle_company_awareness(tag_handled_prompt)

    if memories:
        tag_handled_prompt = handle_memories(tag_handled_prompt, memories)

    if tools:
        tag_handled_prompt += "\n\n# Tools\n"
        tag_handled_prompt += TOOL_PERSISTENCE_PROMPT

        has_web_search = any(type(tool).__name__ == "WebSearchTool" for tool in tools)
        has_internal_search = any(type(tool).__name__ == "SearchTool" for tool in tools)

        if has_web_search or has_internal_search:
            from onyx.prompts.chat_prompts import TOOL_DESCRIPTION_SEARCH_GUIDANCE

            tag_handled_prompt += "\n" + TOOL_DESCRIPTION_SEARCH_GUIDANCE + "\n"

        if has_internal_search:
            from onyx.prompts.chat_prompts import INTERNAL_SEARCH_GUIDANCE

            tag_handled_prompt += "\n" + INTERNAL_SEARCH_GUIDANCE + "\n"

        if has_internal_search and has_web_search:
            from onyx.prompts.chat_prompts import (
                INTERNAL_SEARCH_VS_WEB_SEARCH_GUIDANCE,
            )

            tag_handled_prompt += "\n" + INTERNAL_SEARCH_VS_WEB_SEARCH_GUIDANCE + "\n"

        for tool in tools:
            if type(tool).__name__ == "WebSearchTool":
                from onyx.tools.tool_implementations_v2.web import (
                    WEB_SEARCH_LONG_DESCRIPTION,
                    OPEN_URL_LONG_DESCRIPTION,
                )

                tag_handled_prompt += "\n## web_search\n"
                tag_handled_prompt += WEB_SEARCH_LONG_DESCRIPTION
                tag_handled_prompt += "\n\n## open_url\n"
                tag_handled_prompt += OPEN_URL_LONG_DESCRIPTION
            else:
                # TODO: ToolV2 should make this much cleaner
                from onyx.tools.adapter_v1_to_v2 import tools_to_function_tools

                if tools_to_function_tools([tool]):
                    tag_handled_prompt += (
                        f"\n## {tools_to_function_tools([tool])[0].name}\n"
                    )
                    tag_handled_prompt += tool.description

    tag_handled_prompt += "\n# Reminders"
    if should_cite_documents:
        from onyx.prompts.chat_prompts import REQUIRE_CITATION_STATEMENT

        tag_handled_prompt += "\n\n" + REQUIRE_CITATION_STATEMENT

    tag_handled_prompt += "\n\n" + LONG_CONVERSATION_REMINDER_PROMPT

    return SystemMessage(content=tag_handled_prompt)


def default_build_system_message(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    memories: list[str] | None = None,
) -> SystemMessage | None:
    # Build system prompt from default behavior and custom instructions
    # for backwards compatibility
    system_prompt = (
        prompt_config.custom_instructions
        or prompt_config.default_behavior_system_prompt
    )
    # See https://simonwillison.net/tags/markdown/ for context on why this is needed
    # for OpenAI reasoning models to have correct markdown generation
    if model_needs_formatting_reenabled(llm_config.model_name):
        system_prompt = CODE_BLOCK_MARKDOWN + system_prompt

    tag_handled_prompt = handle_onyx_date_awareness(
        system_prompt,
        prompt_config,
        add_additional_info_if_no_tag=prompt_config.datetime_aware,
    )

    if not tag_handled_prompt:
        return None

    tag_handled_prompt = handle_company_awareness(tag_handled_prompt)

    if memories:
        tag_handled_prompt = handle_memories(tag_handled_prompt, memories)

    return SystemMessage(content=tag_handled_prompt)


def default_build_user_message(
    user_query: str,
    prompt_config: PromptConfig,
    files: list[InMemoryChatFile] = [],
    single_message_history: str | None = None,
) -> HumanMessage:
    history_block = (
        HISTORY_BLOCK.format(history_str=single_message_history)
        if single_message_history
        else ""
    )

    user_prompt = (
        CHAT_USER_CONTEXT_FREE_PROMPT.format(
            history_block=history_block,
            task_prompt=prompt_config.reminder,
            user_query=user_query,
        )
        if prompt_config.reminder
        else user_query
    )

    user_prompt = user_prompt.strip()
    tag_handled_prompt = handle_onyx_date_awareness(user_prompt, prompt_config)
    user_msg = HumanMessage(
        content=(
            build_content_with_imgs(tag_handled_prompt, files)
            if files
            else tag_handled_prompt
        )
    )
    return user_msg


class AnswerPromptBuilder:
    def __init__(
        self,
        user_message: HumanMessage,
        message_history: list[PreviousMessage],
        llm_config: LLMConfig,
        raw_user_query: str,
        raw_user_uploaded_files: list[InMemoryChatFile],
        single_message_history: str | None = None,
        system_message: SystemMessage | None = None,
    ) -> None:
        self.max_tokens = compute_max_llm_input_tokens(llm_config)

        llm_tokenizer = get_tokenizer(
            provider_type=llm_config.model_provider,
            model_name=llm_config.model_name,
        )
        self.llm_config = llm_config
        self.llm_tokenizer_encode_func = cast(
            Callable[[str], list[int]], llm_tokenizer.encode
        )

        self.raw_message_history = message_history
        (
            self.message_history,
            self.history_token_cnts,
        ) = translate_history_to_basemessages(
            message_history,
            exclude_images=not model_supports_image_input(
                self.llm_config.model_name,
                self.llm_config.model_provider,
            ),
        )

        self.update_system_prompt(system_message)
        self.update_user_prompt(user_message)

        self.new_messages_and_token_cnts: list[tuple[BaseMessage, int]] = []

        # used for building a new prompt after a tool-call
        self.raw_user_query = raw_user_query
        self.raw_user_uploaded_files = raw_user_uploaded_files
        self.single_message_history = single_message_history

        # Optional: if the prompt includes explicit context documents (e.g., project files),
        # store them here so downstream streaming can reference them for citation mapping.
        self.context_llm_docs: list[LlmDoc] | None = None

    def update_system_prompt(self, system_message: SystemMessage | None) -> None:
        if not system_message:
            self.system_message_and_token_cnt = None
            return

        self.system_message_and_token_cnt = (
            system_message,
            check_message_tokens(system_message, self.llm_tokenizer_encode_func),
        )

    def update_user_prompt(self, user_message: HumanMessage) -> None:
        self.user_message_and_token_cnt = (
            user_message,
            check_message_tokens(user_message, self.llm_tokenizer_encode_func),
        )

    def append_message(self, message: BaseMessage) -> None:
        """Append a new message to the message history."""
        token_count = check_message_tokens(message, self.llm_tokenizer_encode_func)
        self.new_messages_and_token_cnts.append((message, token_count))

    def get_user_message_content(self) -> str:
        query, _ = message_to_prompt_and_imgs(self.user_message_and_token_cnt[0])
        return query

    def get_message_history(self) -> list[PreviousMessage]:
        """
        Get the message history as a list of PreviousMessage objects.
        """
        message_history = []
        if self.system_message_and_token_cnt:
            tmp = PreviousMessage.from_langchain_msg(*self.system_message_and_token_cnt)
            message_history.append(tmp)
        for i, msg in enumerate(self.message_history):
            tmp = PreviousMessage.from_langchain_msg(msg, self.history_token_cnts[i])
            message_history.append(tmp)
        return message_history

    def build(self) -> list[BaseMessage]:
        if not self.user_message_and_token_cnt:
            raise ValueError("User message must be set before building prompt")

        final_messages_with_tokens: list[tuple[BaseMessage, int]] = []
        if self.system_message_and_token_cnt:
            final_messages_with_tokens.append(self.system_message_and_token_cnt)

        final_messages_with_tokens.extend(
            [
                (self.message_history[i], self.history_token_cnts[i])
                for i in range(len(self.message_history))
            ]
        )

        final_messages_with_tokens.append(self.user_message_and_token_cnt)

        if self.new_messages_and_token_cnts:
            final_messages_with_tokens.extend(self.new_messages_and_token_cnts)

        return drop_messages_history_overflow(
            final_messages_with_tokens, self.max_tokens
        )


# Stores some parts of a prompt builder as needed for tool calls


# TODO: rename this? AnswerConfig maybe?
class LLMCall(BaseModel__v1):
    prompt_builder: AnswerPromptBuilder
    tools: list[Tool]
    force_use_tool: ForceUseTool
    files: list[InMemoryChatFile]
    tool_call_info: list[ToolCallKickoff | ToolResponse | ToolCallFinalResult]
    using_tool_calling_llm: bool

    class Config:
        arbitrary_types_allowed = True
