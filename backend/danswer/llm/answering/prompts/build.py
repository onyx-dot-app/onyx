from collections.abc import Callable
from typing import cast

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from danswer.file_store.models import InMemoryChatFile
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.prompts.citations_prompt import compute_max_llm_input_tokens
from danswer.llm.interfaces import LLMConfig
from danswer.llm.utils import build_content_with_imgs
from danswer.llm.utils import check_message_tokens
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.llm.utils import translate_history_to_basemessages
from danswer.prompts.chat_prompts import CHAT_USER_CONTEXT_FREE_PROMPT
from danswer.prompts.prompt_utils import add_date_time_to_prompt
from danswer.prompts.prompt_utils import drop_messages_history_overflow
from danswer.tools.message import ToolCallSummary


def default_build_system_message(
    prompt_config: PromptConfig,
) -> SystemMessage | None:
    system_prompt = prompt_config.system_prompt.strip()
    if prompt_config.datetime_aware:
        system_prompt = add_date_time_to_prompt(prompt_str=system_prompt)

    if not system_prompt:
        return None

    system_msg = SystemMessage(content=system_prompt)

    return system_msg


def default_build_user_message(
    user_query: str, prompt_config: PromptConfig, files: list[InMemoryChatFile] = []
) -> HumanMessage:
    user_prompt = (
        CHAT_USER_CONTEXT_FREE_PROMPT.format(
            task_prompt=prompt_config.task_prompt, user_query=user_query
        )
        if prompt_config.task_prompt
        else user_query
    )
    user_prompt = user_prompt.strip()
    user_msg = HumanMessage(
        content=build_content_with_imgs(user_prompt, files) if files else user_prompt
    )
    return user_msg


class AnswerPromptBuilder:
    def __init__(
        self, message_history: list[PreviousMessage], llm_config: LLMConfig
    ) -> None:
        self.max_tokens = compute_max_llm_input_tokens(llm_config)

        (
            self.message_history,
            self.history_token_cnts,
        ) = translate_history_to_basemessages(message_history)

        self.system_message_and_token_cnt: tuple[SystemMessage, int] | None = None
        self.user_message_and_token_cnt: tuple[HumanMessage, int] | None = None

        llm_tokenizer = get_default_llm_tokenizer()
        self.llm_tokenizer_encode_func = cast(
            Callable[[str], list[int]], llm_tokenizer.encode
        )

    def update_system_prompt(self, system_message: SystemMessage | None) -> None:
        if not system_message:
            self.system_message_and_token_cnt = None
            return

        self.system_message_and_token_cnt = (
            system_message,
            check_message_tokens(system_message, self.llm_tokenizer_encode_func),
        )

    def update_user_prompt(self, user_message: HumanMessage) -> None:
        if not user_message:
            self.user_message_and_token_cnt = None
            return

        self.user_message_and_token_cnt = (
            user_message,
            check_message_tokens(user_message, self.llm_tokenizer_encode_func),
        )

    def build(
        self, tool_call_summary: ToolCallSummary | None = None
    ) -> list[BaseMessage]:
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

        if tool_call_summary:
            final_messages_with_tokens.append((tool_call_summary.tool_call_request, 0))
            final_messages_with_tokens.append((tool_call_summary.tool_call_result, 0))

        return drop_messages_history_overflow(
            final_messages_with_tokens, self.max_tokens
        )
