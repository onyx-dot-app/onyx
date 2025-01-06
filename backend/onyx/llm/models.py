from typing import TYPE_CHECKING

from langchain.schema.messages import AIMessage
from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage
from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.utils import build_content_with_imgs
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
            tool_call=ToolCallFinalResult(
                tool_name=chat_message.tool_call.tool_name,
                tool_args=chat_message.tool_call.tool_arguments,
                tool_result=chat_message.tool_call.tool_result,
            )
            if chat_message.tool_call
            else None,
        )

    def to_langchain_msg(self) -> BaseMessage:
        content = build_content_with_imgs(self.message, self.files)
        if self.message_type == MessageType.USER:
            return HumanMessage(content=content)
        elif self.message_type == MessageType.ASSISTANT:
            return AIMessage(content=content)
        else:
            return SystemMessage(content=content)
