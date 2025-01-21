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
from danswer.llm.utils import message_to_prompt_and_imgs
from danswer.llm.utils import model_supports_image_input
from danswer.llm.utils import translate_history_to_basemessages
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.prompts.chat_prompts import CHAT_USER_CONTEXT_FREE_PROMPT
from danswer.prompts.prompt_utils import add_date_time_to_prompt
from danswer.prompts.prompt_utils import drop_messages_history_overflow


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
        self,
        user_message: HumanMessage,
        message_history: list[PreviousMessage],
        llm_config: LLMConfig,
        single_message_history: str | None = None,
        raw_user_text: str | None = None,
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

        # for cases where like the QA flow where we want to condense the chat history
        # into a single message rather than a sequence of User / Assistant messages
        self.single_message_history = single_message_history

        self.system_message_and_token_cnt: tuple[SystemMessage, int] | None = None
        self.user_message_and_token_cnt = (
            user_message,
            check_message_tokens(
                user_message,
                self.llm_tokenizer_encode_func,
            ),
        )

        self.new_messages_and_token_cnts: list[tuple[BaseMessage, int]] = []

        self.raw_user_message = (
            HumanMessage(content=raw_user_text)
            if raw_user_text is not None
            else user_message
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
