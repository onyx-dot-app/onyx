from danswer.chat.models import AllCitations
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerContexts
from danswer.chat.models import LLMRelevanceFilterResponse
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.chat.process_message import ChatPacketStream
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.utils.timing import log_function_time
from ee.danswer.server.query_and_chat.models import OneShotQAResponse


@log_function_time()
def gather_stream_for_answer_api(
    packets: ChatPacketStream,
) -> OneShotQAResponse:
    response = OneShotQAResponse()

    answer = ""
    for packet in packets:
        if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.docs = packet
            # Extraneous, provided for backwards compatibility
            response.rephrase = packet.rephrased_query
        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.chat_message_id = packet.message_id
        elif isinstance(packet, LLMRelevanceFilterResponse):
            response.llm_selected_doc_indices = packet.llm_selected_doc_indices
        elif isinstance(packet, AllCitations):
            response.citations = packet.citations
        elif isinstance(packet, DanswerContexts):
            response.contexts = packet

    if answer:
        response.answer = answer

    return response
