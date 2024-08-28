import asyncio
import io
import uuid
from collections.abc import Callable
from collections.abc import Generator

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.chat.chat_utils import create_chat_chain
from danswer.chat.process_message import stream_chat_message
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.constants import FileOrigin
from danswer.configs.constants import MessageType
from danswer.db.chat import create_chat_session
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import delete_chat_session
from danswer.db.chat import get_chat_message
from danswer.db.chat import get_chat_messages_by_session
from danswer.db.chat import get_chat_session_by_id
from danswer.db.chat import get_chat_sessions_by_user
from danswer.db.chat import get_or_create_root_message
from danswer.db.chat import set_as_latest_chat_message
from danswer.db.chat import translate_db_message_to_chat_message_detail
from danswer.db.chat import update_chat_session
from danswer.db.engine import get_session
from danswer.db.feedback import create_chat_message_feedback
from danswer.db.feedback import create_doc_retrieval_feedback
from danswer.db.models import User
from danswer.db.persona import get_persona_by_id
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.document_index.factory import get_default_document_index
from danswer.file_processing.extract_file_text import extract_file_text
from danswer.file_store.file_store import get_default_file_store
from danswer.file_store.models import ChatFileType
from danswer.file_store.models import FileDescriptor
from danswer.llm.answering.prompts.citations_prompt import (
    compute_max_document_tokens_for_persona,
)
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_default_llms
from danswer.llm.factory import get_llms_for_persona
from danswer.llm.headers import get_litellm_additional_request_headers
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.secondary_llm_flows.chat_session_naming import (
    get_renamed_conversation_name,
)
from danswer.server.query_and_chat.models import ChatFeedbackRequest
from danswer.server.query_and_chat.models import ChatMessageIdentifier
from danswer.server.query_and_chat.models import ChatRenameRequest
from danswer.server.query_and_chat.models import ChatSessionCreationRequest
from danswer.server.query_and_chat.models import ChatSessionDetailResponse
from danswer.server.query_and_chat.models import ChatSessionDetails
from danswer.server.query_and_chat.models import ChatSessionsResponse
from danswer.server.query_and_chat.models import ChatSessionUpdateRequest
from danswer.server.query_and_chat.models import CreateChatMessageRequest
from danswer.server.query_and_chat.models import CreateChatSessionID
from danswer.server.query_and_chat.models import LLMOverride
from danswer.server.query_and_chat.models import PromptOverride
from danswer.server.query_and_chat.models import RenameChatSessionResponse
from danswer.server.query_and_chat.models import SearchFeedbackRequest
from danswer.server.query_and_chat.models import UpdateChatSessionThreadRequest
from danswer.server.query_and_chat.token_limit import check_token_rate_limits
from danswer.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/chat")


@router.get("/get-user-chat-sessions")
def get_user_chat_sessions(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    user_id = user.id if user is not None else None

    try:
        chat_sessions = get_chat_sessions_by_user(
            user_id=user_id, deleted=False, db_session=db_session
        )

    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    return ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=chat.id,
                name=chat.description,
                persona_id=chat.persona_id,
                time_created=chat.time_created.isoformat(),
                shared_status=chat.shared_status,
                folder_id=chat.folder_id,
                current_alternate_model=chat.current_alternate_model,
            )
            for chat in chat_sessions
        ]
    )


@router.put("/update-chat-session-model")
def update_chat_session_model(
    update_thread_req: UpdateChatSessionThreadRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id if user is not None else None,
        db_session=db_session,
    )
    chat_session.current_alternate_model = update_thread_req.new_alternate_model

    db_session.add(chat_session)
    db_session.commit()


@router.get("/get-chat-session/{session_id}")
def get_chat_session(
    session_id: int,
    is_shared: bool = False,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionDetailResponse:
    user_id = user.id if user is not None else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=session_id,
            user_id=user_id,
            db_session=db_session,
            is_shared=is_shared,
        )
    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    # for chat-seeding: if the session is unassigned, assign it now. This is done here
    # to avoid another back and forth between FE -> BE before starting the first
    # message generation
    if chat_session.user_id is None and user_id is not None:
        chat_session.user_id = user_id
        db_session.commit()

    session_messages = get_chat_messages_by_session(
        chat_session_id=session_id,
        user_id=user_id,
        db_session=db_session,
        # we already did a permission check above with the call to
        # `get_chat_session_by_id`, so we can skip it here
        skip_permission_check=True,
        # we need the tool call objs anyways, so just fetch them in a single call
        prefetch_tool_calls=True,
    )

    return ChatSessionDetailResponse(
        chat_session_id=session_id,
        description=chat_session.description,
        persona_id=chat_session.persona_id,
        persona_name=chat_session.persona.name,
        current_alternate_model=chat_session.current_alternate_model,
        messages=[
            translate_db_message_to_chat_message_detail(
                msg, remove_doc_content=is_shared  # if shared, don't leak doc content
            )
            for msg in session_messages
        ],
        time_created=chat_session.time_created,
        shared_status=chat_session.shared_status,
    )


@router.post("/create-chat-session")
def create_new_chat_session(
    chat_session_creation_request: ChatSessionCreationRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreateChatSessionID:
    user_id = user.id if user is not None else None
    try:
        new_chat_session = create_chat_session(
            db_session=db_session,
            description=chat_session_creation_request.description
            or "",  # Leave the naming till later to prevent delay
            user_id=user_id,
            persona_id=chat_session_creation_request.persona_id,
        )
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail="Invalid Persona provided.")

    return CreateChatSessionID(chat_session_id=new_chat_session.id)


@router.put("/rename-chat-session")
def rename_chat_session(
    rename_req: ChatRenameRequest,
    request: Request,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RenameChatSessionResponse:
    name = rename_req.name
    chat_session_id = rename_req.chat_session_id
    user_id = user.id if user is not None else None

    if name:
        update_chat_session(
            db_session=db_session,
            user_id=user_id,
            chat_session_id=chat_session_id,
            description=name,
        )
        return RenameChatSessionResponse(new_name=name)

    final_msg, history_msgs = create_chat_chain(
        chat_session_id=chat_session_id, db_session=db_session
    )
    full_history = history_msgs + [final_msg]

    try:
        llm, _ = get_default_llms(
            additional_headers=get_litellm_additional_request_headers(request.headers)
        )
    except GenAIDisabledException:
        # This may be longer than what the LLM tends to produce but is the most
        # clear thing we can do
        return RenameChatSessionResponse(new_name=full_history[0].message)

    new_name = get_renamed_conversation_name(full_history=full_history, llm=llm)

    update_chat_session(
        db_session=db_session,
        user_id=user_id,
        chat_session_id=chat_session_id,
        description=new_name,
    )

    return RenameChatSessionResponse(new_name=new_name)


@router.patch("/chat-session/{session_id}")
def patch_chat_session(
    session_id: int,
    chat_session_update_req: ChatSessionUpdateRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None
    update_chat_session(
        db_session=db_session,
        user_id=user_id,
        chat_session_id=session_id,
        sharing_status=chat_session_update_req.sharing_status,
    )
    return None


@router.delete("/delete-chat-session/{session_id}")
def delete_chat_session_by_id(
    session_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None
    delete_chat_session(user_id, session_id, db_session)


async def is_disconnected(request: Request) -> Callable[[], bool]:
    main_loop = asyncio.get_event_loop()

    def is_disconnected_sync() -> bool:
        future = asyncio.run_coroutine_threadsafe(request.is_disconnected(), main_loop)
        try:
            return not future.result(timeout=0.01)
        except asyncio.TimeoutError:
            logger.error("Asyncio timed out")
            return True
        except Exception as e:
            error_msg = str(e)
            logger.critical(
                f"An unexpected error occured with the disconnect check coroutine: {error_msg}"
            )
            return True

    return is_disconnected_sync


@router.post("/send-message")
def handle_new_chat_message(
    chat_message_req: CreateChatMessageRequest,
    request: Request,
    user: User | None = Depends(current_user),
    _: None = Depends(check_token_rate_limits),
    is_disconnected_func: Callable[[], bool] = Depends(is_disconnected),
) -> StreamingResponse:
    """This endpoint is both used for all the following purposes:
    - Sending a new message in the session
    - Regenerating a message in the session (just send the same one again)
    - Editing a message (similar to regenerating but sending a different message)
    - Kicking off a seeded chat session (set `use_existing_user_message`)
    To avoid extra overhead/latency, this assumes (and checks) that previous messages on the path
    have already been set as latest"""
    logger.debug(f"Received new chat message: {chat_message_req.message}")

    if (
        not chat_message_req.message
        and chat_message_req.prompt_id is not None
        and not chat_message_req.use_existing_user_message
    ):
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    import json

    def stream_generator() -> Generator[str, None, None]:
        try:
            for packet in stream_chat_message(
                new_msg_req=chat_message_req,
                user=user,
                use_existing_user_message=chat_message_req.use_existing_user_message,
                litellm_additional_headers=get_litellm_additional_request_headers(
                    request.headers
                ),
                is_connected=is_disconnected_func,
            ):
                yield json.dumps(packet) if isinstance(packet, dict) else packet

        except Exception as e:
            logger.exception(f"Error in chat message streaming: {e}")
            yield json.dumps({"error": str(e)})

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.put("/set-message-as-latest")
def set_message_as_latest(
    message_identifier: ChatMessageIdentifier,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None

    chat_message = get_chat_message(
        chat_message_id=message_identifier.message_id,
        user_id=user_id,
        db_session=db_session,
    )

    set_as_latest_chat_message(
        chat_message=chat_message,
        user_id=user_id,
        db_session=db_session,
    )


@router.post("/create-chat-message-feedback")
def create_chat_feedback(
    feedback: ChatFeedbackRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None

    create_chat_message_feedback(
        is_positive=feedback.is_positive,
        feedback_text=feedback.feedback_text,
        predefined_feedback=feedback.predefined_feedback,
        chat_message_id=feedback.chat_message_id,
        user_id=user_id,
        db_session=db_session,
    )


@router.post("/document-search-feedback")
def create_search_feedback(
    feedback: SearchFeedbackRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    """This endpoint isn't protected - it does not check if the user has access to the document
    Users could try changing boosts of arbitrary docs but this does not leak any data.
    """

    curr_ind_name, sec_ind_name = get_both_index_names(db_session)
    document_index = get_default_document_index(
        primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
    )

    create_doc_retrieval_feedback(
        message_id=feedback.message_id,
        document_id=feedback.document_id,
        document_rank=feedback.document_rank,
        clicked=feedback.click,
        feedback=feedback.search_feedback,
        document_index=document_index,
        db_session=db_session,
    )


class MaxSelectedDocumentTokens(BaseModel):
    max_tokens: int


@router.get("/max-selected-document-tokens")
def get_max_document_tokens(
    persona_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MaxSelectedDocumentTokens:
    try:
        persona = get_persona_by_id(
            persona_id=persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Persona not found")

    return MaxSelectedDocumentTokens(
        max_tokens=compute_max_document_tokens_for_persona(persona),
    )


"""Endpoints for chat seeding"""


class ChatSeedRequest(BaseModel):
    # standard chat session stuff
    persona_id: int
    prompt_id: int | None = None

    # overrides / seeding
    llm_override: LLMOverride | None = None
    prompt_override: PromptOverride | None = None
    description: str | None = None
    message: str | None = None

    # TODO: support this
    # initial_message_retrieval_options: RetrievalDetails | None = None


class ChatSeedResponse(BaseModel):
    redirect_url: str


@router.post("/seed-chat-session")
def seed_chat(
    chat_seed_request: ChatSeedRequest,
    # NOTE: realistically, this will be an API key not an actual user
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSeedResponse:
    try:
        new_chat_session = create_chat_session(
            db_session=db_session,
            description=chat_seed_request.description or "",
            user_id=None,  # this chat session is "unassigned" until a user visits the web UI
            persona_id=chat_seed_request.persona_id,
            llm_override=chat_seed_request.llm_override,
            prompt_override=chat_seed_request.prompt_override,
        )
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail="Invalid Persona provided.")

    if chat_seed_request.message is not None:
        root_message = get_or_create_root_message(
            chat_session_id=new_chat_session.id, db_session=db_session
        )
        llm, fast_llm = get_llms_for_persona(persona=new_chat_session.persona)

        tokenizer = get_tokenizer(
            model_name=llm.config.model_name,
            provider_type=llm.config.model_provider,
        )
        token_count = len(tokenizer.encode(chat_seed_request.message))

        create_new_chat_message(
            chat_session_id=new_chat_session.id,
            parent_message=root_message,
            prompt_id=chat_seed_request.prompt_id
            or (
                new_chat_session.persona.prompts[0].id
                if new_chat_session.persona.prompts
                else None
            ),
            message=chat_seed_request.message,
            token_count=token_count,
            message_type=MessageType.USER,
            db_session=db_session,
        )

    return ChatSeedResponse(
        redirect_url=f"{WEB_DOMAIN}/chat?chatId={new_chat_session.id}&seeded=true"
    )


"""File upload"""


@router.post("/file")
def upload_files_for_chat(
    files: list[UploadFile],
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> dict[str, list[FileDescriptor]]:
    image_content_types = {"image/jpeg", "image/png", "image/webp"}
    text_content_types = {
        "text/plain",
        "text/csv",
        "text/markdown",
        "text/x-markdown",
        "text/x-config",
        "text/tab-separated-values",
        "application/json",
        "application/xml",
        "text/xml",
        "application/x-yaml",
    }
    document_content_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "message/rfc822",
        "application/epub+zip",
    }

    allowed_content_types = image_content_types.union(text_content_types).union(
        document_content_types
    )

    for file in files:
        if file.content_type not in allowed_content_types:
            if file.content_type in image_content_types:
                error_detail = "Unsupported image file type. Supported image types include .jpg, .jpeg, .png, .webp."
            elif file.content_type in text_content_types:
                error_detail = "Unsupported text file type. Supported text types include .txt, .csv, .md, .mdx, .conf, "
                ".log, .tsv."
            else:
                error_detail = (
                    "Unsupported document file type. Supported document types include .pdf, .docx, .pptx, .xlsx, "
                    ".json, .xml, .yml, .yaml, .eml, .epub."
                )
            raise HTTPException(status_code=400, detail=error_detail)

        if (
            file.content_type in image_content_types
            and file.size
            and file.size > 20 * 1024 * 1024
        ):
            raise HTTPException(
                status_code=400,
                detail="File size must be less than 20MB",
            )

    file_store = get_default_file_store(db_session)

    file_info: list[tuple[str, str | None, ChatFileType]] = []
    for file in files:
        if file.content_type in image_content_types:
            file_type = ChatFileType.IMAGE
        elif file.content_type in document_content_types:
            file_type = ChatFileType.DOC
        else:
            file_type = ChatFileType.PLAIN_TEXT

        # store the raw file
        file_id = str(uuid.uuid4())
        file_store.save_file(
            file_name=file_id,
            content=file.file,
            display_name=file.filename,
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type=file.content_type or file_type.value,
        )

        # if the file is a doc, extract text and store that so we don't need
        # to re-extract it every time we send a message
        if file_type == ChatFileType.DOC:
            extracted_text = extract_file_text(file_name=file.filename, file=file.file)
            text_file_id = str(uuid.uuid4())
            file_store.save_file(
                file_name=text_file_id,
                content=io.BytesIO(extracted_text.encode()),
                display_name=file.filename,
                file_origin=FileOrigin.CHAT_UPLOAD,
                file_type="text/plain",
            )
            # for DOC type, just return this for the FileDescriptor
            # as we would always use this as the ID to attach to the
            # message
            file_info.append((text_file_id, file.filename, ChatFileType.PLAIN_TEXT))
        else:
            file_info.append((file_id, file.filename, file_type))

    return {
        "files": [
            {"id": file_id, "type": file_type, "name": file_name}
            for file_id, file_name, file_type in file_info
        ]
    }


@router.get("/file/{file_id}")
def fetch_chat_file(
    file_id: str,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> Response:
    file_store = get_default_file_store(db_session)
    file_io = file_store.read_file(file_id, mode="b")
    # NOTE: specifying "image/jpeg" here, but it still works for pngs
    # TODO: do this properly
    return Response(content=file_io.read(), media_type="image/jpeg")
