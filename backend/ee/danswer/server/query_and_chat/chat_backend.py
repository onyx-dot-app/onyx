import re

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.chat.chat_utils import create_chat_chain
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.chat.process_message import stream_chat_message_objects
from danswer.db.chat import get_or_create_root_message
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.search.models import OptionalSearchSetting
from danswer.search.models import RetrievalDetails
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.server.query_and_chat.models import CreateChatMessageRequest
from danswer.utils.logger import setup_logger
from ee.danswer.server.query_and_chat.models import BasicCreateChatMessageRequest
from ee.danswer.server.query_and_chat.models import ChatBasicResponse
from ee.danswer.server.query_and_chat.models import SimpleDoc

logger = setup_logger()

router = APIRouter(prefix="/chat")


def translate_doc_response_to_simple_doc(
    doc_response: QADocsResponse,
) -> list[SimpleDoc]:
    return [
        SimpleDoc(
            id=doc.document_id,
            semantic_identifier=doc.semantic_identifier,
            link=doc.link,
            blurb=doc.blurb,
            match_highlights=[
                highlight for highlight in doc.match_highlights if highlight
            ],
            source_type=doc.source_type,
        )
        for doc in doc_response.top_documents
    ]


def remove_answer_citations(answer: str) -> str:
    pattern = r"\s*\[\[\d+\]\]\(http[s]?://[^\s]+\)"

    return re.sub(pattern, "", answer)


@router.post("/send-message-simple-api")
def handle_simplified_chat_message(
    chat_message_req: BasicCreateChatMessageRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatBasicResponse:
    """This is a Non-Streaming version that only gives back a minimal set of information"""
    logger.info(f"Received new simple api chat message: {chat_message_req.message}")

    if not chat_message_req.message:
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    try:
        parent_message, _ = create_chat_chain(
            chat_session_id=chat_message_req.chat_session_id, db_session=db_session
        )
    except Exception:
        parent_message = get_or_create_root_message(
            chat_session_id=chat_message_req.chat_session_id, db_session=db_session
        )

    if (
        chat_message_req.retrieval_options is None
        and chat_message_req.search_doc_ids is None
    ):
        retrieval_options: RetrievalDetails | None = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
        )
    else:
        retrieval_options = chat_message_req.retrieval_options

    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_message_req.chat_session_id,
        parent_message_id=parent_message.id,
        message=chat_message_req.message,
        file_descriptors=[],
        prompt_id=None,
        search_doc_ids=chat_message_req.search_doc_ids,
        retrieval_options=retrieval_options,
        query_override=chat_message_req.query_override,
        chunks_above=chat_message_req.chunks_above,
        chunks_below=chat_message_req.chunks_below,
        full_doc=chat_message_req.full_doc,
    )

    packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
    )

    response = ChatBasicResponse()

    answer = ""
    for packet in packets:
        if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.simple_search_docs = translate_doc_response_to_simple_doc(packet)
        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.message_id = packet.message_id

    response.answer = answer
    if answer:
        response.answer_citationless = remove_answer_citations(answer)

    return response
