from langchain.schema.messages import AIMessage
from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import build_content_with_imgs
from onyx.prompts.direct_qa_prompts import PARAMATERIZED_PROMPT
from onyx.prompts.direct_qa_prompts import PARAMATERIZED_PROMPT_WITHOUT_CONTEXT


def build_dummy_prompt(
    system_prompt: str, task_prompt: str, retrieval_disabled: bool
) -> str:
    if retrieval_disabled:
        return PARAMATERIZED_PROMPT_WITHOUT_CONTEXT.format(
            user_query="<USER_QUERY>",
            system_prompt=system_prompt,
            task_prompt=task_prompt,
        ).strip()

    return PARAMATERIZED_PROMPT.format(
        context_docs_str="<CONTEXT_DOCS>",
        user_query="<USER_QUERY>",
        system_prompt=system_prompt,
        task_prompt=task_prompt,
    ).strip()


def translate_onyx_msg_to_langchain(
    msg: ChatMessage | PreviousMessage,
) -> BaseMessage:
    files: list[InMemoryChatFile] = []

    # If the message is a `ChatMessage`, it doesn't have the downloaded files
    # attached. Just ignore them for now.
    if not isinstance(msg, ChatMessage):
        files = msg.files
    content = build_content_with_imgs(msg.message, files, message_type=msg.message_type)

    if msg.message_type == MessageType.SYSTEM:
        raise ValueError("System messages are not currently part of history")
    if msg.message_type == MessageType.ASSISTANT:
        return AIMessage(content=content)
    if msg.message_type == MessageType.USER:
        return HumanMessage(content=content)

    raise ValueError(f"New message type {msg.message_type} not handled")


def translate_history_to_basemessages(
    history: list[ChatMessage] | list["PreviousMessage"],
) -> tuple[list[BaseMessage], list[int]]:
    history_basemessages = [
        translate_onyx_msg_to_langchain(msg) for msg in history if msg.token_count != 0
    ]
    history_token_counts = [msg.token_count for msg in history if msg.token_count != 0]
    return history_basemessages, history_token_counts
