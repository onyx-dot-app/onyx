from agents import RawResponsesStreamEvent

from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import PacketObj
from onyx.server.query_and_chat.streaming_models import SectionEnd


def default_packet_translation(ev: object) -> PacketObj | None:
    if isinstance(ev, RawResponsesStreamEvent):
        # TODO: might need some variation here for different types of models
        # OpenAI packet translator
        obj: PacketObj | None = None
        if ev.data.type == "response.created":
            obj = MessageStart(type="message_start", content="", final_documents=None)
        elif ev.data.type == "response.output_text.delta":
            obj = MessageDelta(type="message_delta", content=ev.data.delta)
        elif ev.data.type == "response.output_item.done":
            obj = SectionEnd(type="section_end")
        return obj
    return None
