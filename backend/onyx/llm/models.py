from typing import TYPE_CHECKING

from langchain.schema.messages import AIMessage
from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage
from pydantic import BaseModel

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.configs.constants import MessageType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.utils import build_content_with_imgs
from onyx.llm.utils import message_to_string
from onyx.tools.models import ToolCallFinalResult

if TYPE_CHECKING:
    from onyx.db.models import ChatMessage


class PreviousMessage(BaseModel):
    """Simplified version of `ChatMessage`"""

    message: str
    token_count: int
    message_type: MessageType
    files: list[InMemoryChatFile]
    tool_call: ToolCallFinalResult | None
    refined_answer_improvement: bool | None
    research_answer_purpose: ResearchAnswerPurpose | None

    @classmethod
    def from_chat_message(
        cls, chat_message: "ChatMessage", available_files: list[InMemoryChatFile]
    ) -> "PreviousMessage":
        message_file_ids = (
            [file["id"] for file in chat_message.files] if chat_message.files else []
        )
        return cls(
            message=chat_message.message,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
            files=[
                file
                for file in available_files
                if str(file.file_id) in message_file_ids
            ],
            tool_call=(
                ToolCallFinalResult(
                    tool_name=chat_message.tool_call.tool_name,
                    tool_args=chat_message.tool_call.tool_arguments,
                    tool_result=chat_message.tool_call.tool_result,
                )
                if chat_message.tool_call
                else None
            ),
            refined_answer_improvement=chat_message.refined_answer_improvement,
            research_answer_purpose=chat_message.research_answer_purpose,
        )

    def to_agent_sdk_msg(self) -> dict:
        message_type_to_agent_sdk_role = {
            MessageType.USER: "user",
            MessageType.SYSTEM: "system",
            MessageType.ASSISTANT: "assistant",
        }
        # TODO: Use native format for files and images
        content = build_content_with_imgs(self.message, self.files)
        if self.message_type in message_type_to_agent_sdk_role:
            role = message_type_to_agent_sdk_role[self.message_type]
            return {
                "role": role,
                "content": content,
            }
        raise ValueError(f"Unknown message type: {self.message_type}")

    def to_langchain_msg(self) -> BaseMessage:
        content = build_content_with_imgs(self.message, self.files)
        if self.message_type == MessageType.USER:
            return HumanMessage(content=content)
        elif self.message_type == MessageType.ASSISTANT:
            return AIMessage(content=content)
        else:
            return SystemMessage(content=content)

    # TODO: deprecate langchain
    @classmethod
    def from_langchain_msg(
        cls, msg: BaseMessage, token_count: int
    ) -> "PreviousMessage":
        message_type = MessageType.SYSTEM
        if isinstance(msg, HumanMessage):
            message_type = MessageType.USER
        elif isinstance(msg, AIMessage):
            message_type = MessageType.ASSISTANT

        message = message_to_string(msg)
        return cls(
            message=message,
            token_count=token_count,
            message_type=message_type,
            files=[],
            tool_call=None,
            refined_answer_improvement=None,
            research_answer_purpose=None,
        )
