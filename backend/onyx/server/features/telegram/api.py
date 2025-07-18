import time
import uuid
import io
import json
from typing import Callable, Generator

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi import Depends
from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from telebot import TeleBot

from onyx.auth.users import current_user, current_admin_user
from onyx.chat.chat_utils import extract_headers
from onyx.chat.process_message import stream_chat_message
from onyx.configs.constants import MilestoneRecordType, FileOrigin, DocumentSource
from onyx.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS
from onyx.connectors.models import InputType
from onyx.db.chat import create_chat_session
from onyx.db.connector import create_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import create_credential
from onyx.db.engine import get_session, get_session_with_tenant
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.db.telegram import get_user_telegram_api_key_by_user_id, add_user_telegram_api_key, check_api_token, \
    get_user_by_telegram_api_key
from onyx.db.user_documents import create_user_files
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor, ChatFileType
from onyx.server.documents.models import ConnectorBase, CredentialBase
from onyx.server.features.telegram.models import TelegramTokenSettings
from onyx.server.features.telegram.store import load_telegram_settings, store_telegram_settings
from onyx.server.query_and_chat.chat_backend import is_connected, RECENT_DOCS_FOLDER_ID
from onyx.server.query_and_chat.models import ChatSessionCreationRequest, CreateChatSessionID, CreateChatMessageRequest
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.utils.headers import get_custom_tool_additional_request_headers, get_litellm_additional_request_headers
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

basic_router = APIRouter(prefix="/telegram")


@basic_router.get("")
async def get_telegram_api_token(
        user: User = Depends(current_user),
        db_session: Session = Depends(get_session)
):
    telegram_settings = load_telegram_settings()
    user_token = get_user_telegram_api_key_by_user_id(user.id, db_session)

    if user_token is None:
        user_token = add_user_telegram_api_key(user.id, db_session)

    bot = TeleBot(telegram_settings.token)

    me = bot.get_me()

    bot_url = f"https://t.me/{me.username}?start={user_token.api_key}"

    return {"token": user_token.api_key, "url": bot_url}


@basic_router.post("/token")
async def edit_telegram_bot_token(telegram_settings: TelegramTokenSettings,
                                  _: User = Depends(current_admin_user)):
    store_telegram_settings(telegram_settings)

    return {"token": telegram_settings.token}


@basic_router.get("/token")
async def get_telegram_bot_token(_: User = Depends(current_admin_user)):
    telegram_settings = load_telegram_settings()

    return {"token": telegram_settings.token}


@basic_router.post("/create-chat-session")
def create_new_chat_session(
    token: str,
    chat_session_creation_request: ChatSessionCreationRequest,
    db_session: Session = Depends(get_session),
) -> CreateChatSessionID:
    if not check_api_token(token, db_session):
        raise HTTPException(401, "Invalid token")

    user = get_user_by_telegram_api_key(token, db_session)
    try:
        new_chat_session = create_chat_session(
            db_session=db_session,
            user_id=user.id if user else None,
            description=chat_session_creation_request.description
            or "",  # Leave the naming till later to prevent delay
            persona_id=chat_session_creation_request.persona_id,
        )
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail="Invalid Persona provided.")

    return CreateChatSessionID(chat_session_id=new_chat_session.id)


@basic_router.post("/send-message")
def handle_new_chat_message(
    token: str,
    chat_message_req: CreateChatMessageRequest,
    request: Request,
    db_session: Session = Depends(get_session),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    is_connected_func: Callable[[], bool] = Depends(is_connected),
) -> StreamingResponse:
    """
    This endpoint is both used for all the following purposes:
    - Sending a new message in the session
    - Regenerating a message in the session (just send the same one again)
    - Editing a message (similar to regenerating but sending a different message)
    - Kicking off a seeded chat session (set `use_existing_user_message`)

    Assumes that previous messages have been set as the latest to minimize overhead.

    Args:
        chat_message_req (CreateChatMessageRequest): Details about the new chat message.
        request (Request): The current HTTP request context.
        user (User | None): The current user, obtained via dependency injection.
        _ (None): Rate limit check is run if user/group/global rate limits are enabled.
        is_connected_func (Callable[[], bool]): Function to check client disconnection,
            used to stop the streaming response if the client disconnects.

    Returns:
        StreamingResponse: Streams the response to the new chat message.
    """
    if not check_api_token(token, db_session):
        raise HTTPException(401, "Invalid token")
    user = get_user_by_telegram_api_key(token, db_session)
    tenant_id = get_current_tenant_id()
    logger.debug(f"Received new chat message: {chat_message_req.message}")

    if (
        not chat_message_req.message
        and chat_message_req.prompt_id is not None
        and not chat_message_req.use_existing_user_message
    ):
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        create_milestone_and_report(
            user=user,
            distinct_id=tenant_id or "N/A",
            event_type=MilestoneRecordType.RAN_QUERY,
            properties=None,
            db_session=db_session,
        )

    def stream_generator() -> Generator[str, None, None]:
        try:
            for packet in stream_chat_message(
                new_msg_req=chat_message_req,
                user=user,
                litellm_additional_headers=extract_headers(
                    request.headers, LITELLM_PASS_THROUGH_HEADERS
                ),
                custom_tool_additional_headers=get_custom_tool_additional_request_headers(
                    request.headers
                ),
                is_connected=is_connected_func,
            ):
                yield packet

        except Exception as e:
            logger.exception("Error in chat message streaming")
            yield json.dumps({"error": str(e)})

        finally:
            logger.debug("Stream generator finished")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@basic_router.post("/file")
def upload_files_for_chat(
    token: str,
    files: list[UploadFile],
    db_session: Session = Depends(get_session),
) -> dict[str, list[FileDescriptor]]:
    if not check_api_token(token, db_session):
        raise HTTPException(401, "Invalid token")

    user = get_user_by_telegram_api_key(token, db_session)
    image_content_types = {"image/jpeg", "image/png", "image/webp"}
    csv_content_types = {"text/csv"}
    text_content_types = {
        "text/plain",
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

    allowed_content_types = (
        image_content_types.union(text_content_types)
        .union(document_content_types)
        .union(csv_content_types)
    )

    for file in files:
        if not file.content_type:
            raise HTTPException(status_code=400, detail="File content type is required")

        if file.content_type not in allowed_content_types:
            if file.content_type in image_content_types:
                error_detail = "Unsupported image file type. Supported image types include .jpg, .jpeg, .png, .webp."
            elif file.content_type in text_content_types:
                error_detail = "Unsupported text file type."
            elif file.content_type in csv_content_types:
                error_detail = "Unsupported CSV file type."
            else:
                error_detail = "Unsupported document file type."
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
        file_type = (
            ChatFileType.IMAGE
            if file.content_type in image_content_types
            else (
                ChatFileType.CSV
                if file.content_type in csv_content_types
                else (
                    ChatFileType.DOC
                    if file.content_type in document_content_types
                    else ChatFileType.PLAIN_TEXT
                )
            )
        )

        file_content = file.file.read()  # Read the file content

        # NOTE: Image conversion to JPEG used to be enforced here.
        # This was removed to:
        # 1. Preserve original file content for downloads
        # 2. Maintain transparency in formats like PNG
        # 3. Ameliorate issue with file conversion
        file_content_io = io.BytesIO(file_content)

        new_content_type = file.content_type

        # Store the file normally
        file_id = str(uuid.uuid4())
        file_store.save_file(
            file_name=file_id,
            content=file_content_io,
            display_name=file.filename,
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type=new_content_type or file_type.value,
        )

        # 4) If the file is a doc, extract text and store that separately
        if file_type == ChatFileType.DOC:
            # Re-wrap bytes in a fresh BytesIO so we start at position 0
            extracted_text_io = io.BytesIO(file_content)
            extracted_text = extract_file_text(
                file=extracted_text_io,  # use the bytes we already read
                file_name=file.filename or "",
            )
            text_file_id = str(uuid.uuid4())

            file_store.save_file(
                file_name=text_file_id,
                content=io.BytesIO(extracted_text.encode()),
                display_name=file.filename,
                file_origin=FileOrigin.CHAT_UPLOAD,
                file_type="text/plain",
            )
            # Return the text file as the "main" file descriptor for doc types
            file_info.append((text_file_id, file.filename, ChatFileType.PLAIN_TEXT))
        else:
            file_info.append((file_id, file.filename, file_type))

        # 5) Create a user file for each uploaded file
        user_files = create_user_files([file], RECENT_DOCS_FOLDER_ID, None, db_session)
        for user_file in user_files:
            # 6) Create connector
            connector_base = ConnectorBase(
                name=f"UserFile-{int(time.time())}",
                source=DocumentSource.FILE,
                input_type=InputType.LOAD_STATE,
                connector_specific_config={
                    "file_locations": [user_file.file_id],
                },
                refresh_freq=None,
                prune_freq=None,
                indexing_start=None,
            )
            connector = create_connector(
                db_session=db_session,
                connector_data=connector_base,
            )

            # 7) Create credential
            credential_info = CredentialBase(
                credential_json={},
                admin_public=True,
                source=DocumentSource.FILE,
                curator_public=True,
                groups=[],
                name=f"UserFileCredential-{int(time.time())}",
                is_user_file=True,
            )
            credential = create_credential(credential_info, None, db_session)

            # 8) Create connector credential pair
            cc_pair = add_credential_to_connector(
                db_session=db_session,
                user=user,
                connector_id=connector.id,
                credential_id=credential.id,
                cc_pair_name=f"UserFileCCPair-{int(time.time())}",
                access_type=AccessType.PRIVATE,
                auto_sync_options=None,
                groups=[],
            )
            user_file.cc_pair_id = cc_pair.data
            db_session.commit()

    return {
        "files": [
            {"id": file_id, "type": file_type, "name": file_name}
            for file_id, file_name, file_type in file_info
        ]
    }
