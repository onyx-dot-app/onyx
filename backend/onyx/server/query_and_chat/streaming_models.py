from pydantic import BaseModel

from onyx.chat.models import LlmDoc


class BaseObj(BaseModel):
    type: str = ""


"""Basic Message Packets"""


class MessageStart(BaseObj):
    id: str
    type: str = "message_start"
    content: str


class MessageDelta(BaseObj):
    content: str
    type: str = "message_delta"


class MessageEnd(BaseObj):
    type: str = "message_end"


"""Control Packets"""


class Stop(BaseObj):
    type: str = "stop"


"""Tool Packets"""


class ToolStart(BaseObj):
    type: str = "tool_start"

    tool_name: str
    tool_icon: str

    # if left blank, we will use the tool name
    tool_main_description: str | None = None


class ToolDelta(BaseObj):
    type: str = "tool_delta"

    queries: list[str] | None = None
    documents: list[LlmDoc] | None = None
    images: list[dict[str, str]] | None = None


class ToolEnd(BaseObj):
    type: str = "tool_end"


ObjTypes = (
    MessageStart | MessageDelta | MessageEnd | Stop | ToolStart | ToolDelta | ToolEnd
)


class Packet(BaseModel):
    ind: int
    obj: ObjTypes
