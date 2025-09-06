from typing import Literal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.constants import MessageType
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_message
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ChatMessage
from onyx.db.models import User
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger


logger = setup_logger()


router = APIRouter()


class RunRequest(BaseModel):
    assistant_id: int
    model: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    tools: Optional[list[dict]] = None
    metadata: Optional[dict] = None


RunStatus = Literal[
    "queued",
    "in_progress",
    "requires_action",
    "cancelling",
    "cancelled",
    "failed",
    "completed",
    "expired",
]


class RunResponse(BaseModel):
    id: str
    object: Literal["thread.run"]
    created_at: int
    assistant_id: int
    thread_id: UUID
    status: RunStatus
    started_at: Optional[int] = None
    expires_at: Optional[int] = None
    cancelled_at: Optional[int] = None
    failed_at: Optional[int] = None
    completed_at: Optional[int] = None
    last_error: Optional[dict] = None
    model: str
    instructions: str
    tools: list[dict]
    file_ids: list[str]
    metadata: Optional[dict] = None


def process_run_in_background(
    message_id: int,
    parent_message_id: int,
    chat_session_id: UUID,
    assistant_id: int,
    instructions: str,
    tools: list[dict],
    user: User | None,
    db_session: Session,
) -> None:
    # Get the latest message in the chat session
    _ = get_chat_session_by_id(
        chat_session_id=chat_session_id,
        user_id=user.id if user else None,
        db_session=db_session,
    )

    search_tool_retrieval_details = RetrievalDetails()
    for tool in tools:
        if tool["type"] == SearchTool.__name__ and (
            retrieval_details := tool.get("retrieval_details")
        ):
            search_tool_retrieval_details = RetrievalDetails.model_validate(
                retrieval_details
            )
            break

    new_msg_req = CreateChatMessageRequest(
        chat_session_id=chat_session_id,
        parent_message_id=int(parent_message_id) if parent_message_id else None,
        message=instructions,
        file_descriptors=[],
        search_doc_ids=None,
        retrieval_options=search_tool_retrieval_details,  # Adjust as needed
        rerank_settings=None,
        query_override=None,
        regenerate=None,
        llm_override=None,
        prompt_override=None,
        alternate_assistant_id=assistant_id,
        use_existing_user_message=True,
        existing_assistant_message_id=message_id,
    )

    run_message = get_chat_message(message_id, user.id if user else None, db_session)
    try:
        for packet in stream_chat_message_objects(
            new_msg_req=new_msg_req,
            user=user,
            db_session=db_session,
        ):
            if isinstance(packet, ChatMessageDetail):
                # Update the run status and message content
                run_message = get_chat_message(
                    message_id, user.id if user else None, db_session
                )
                if run_message:
                    # this handles cancelling
                    if run_message.error:
                        return

                    run_message.message = packet.message
                    run_message.message_type = MessageType.ASSISTANT
                    db_session.commit()
    except Exception as e:
        logger.exception("Error processing run in background")
        run_message.error = str(e)
        db_session.commit()
        return

    db_session.refresh(run_message)
    if run_message.token_count == 0:
        run_message.error = "No tokens generated"
        db_session.commit()


@router.post("/threads/{thread_id}/runs")
def create_run(
    thread_id: UUID,
    run_request: RunRequest,
    background_tasks: BackgroundTasks,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RunResponse:
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=thread_id,
            user_id=user.id if user else None,
            db_session=db_session,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Thread not found")

    chat_messages = get_chat_messages_by_session(
        chat_session_id=chat_session.id,
        user_id=user.id if user else None,
        db_session=db_session,
    )
    latest_message = (
        chat_messages[-1]
        if chat_messages
        else get_or_create_root_message(chat_session.id, db_session)
    )

    # Create a new "run" (chat message) in the session
    new_message = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=latest_message,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
        commit=False,
    )
    db_session.flush()
    latest_message.latest_child_message = new_message.id
    db_session.commit()

    # Schedule the background task
    background_tasks.add_task(
        process_run_in_background,
        new_message.id,
        latest_message.id,
        chat_session.id,
        run_request.assistant_id,
        run_request.instructions or "",
        run_request.tools or [],
        user,
        db_session,
    )

    return RunResponse(
        id=str(new_message.id),
        object="thread.run",
        created_at=int(new_message.time_sent.timestamp()),
        assistant_id=run_request.assistant_id,
        thread_id=chat_session.id,
        status="queued",
        model=run_request.model or "default_model",
        instructions=run_request.instructions or "",
        tools=run_request.tools or [],
        file_ids=[],
        metadata=run_request.metadata,
    )


@router.get("/threads/{thread_id}/runs/{run_id}")
def retrieve_run(
    thread_id: UUID,
    run_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RunResponse:
    # Retrieve the chat message (which represents a "run" in DAnswer)
    chat_message = get_chat_message(
        chat_message_id=int(run_id),  # Convert string run_id to int
        user_id=user.id if user else None,
        db_session=db_session,
    )
    if not chat_message:
        raise HTTPException(status_code=404, detail="Run not found")

    chat_session = chat_message.chat_session

    # Map DAnswer status to OpenAI status
    run_status: RunStatus = "queued"
    if chat_message.message:
        run_status = "in_progress"
    if chat_message.token_count != 0:
        run_status = "completed"
    if chat_message.error:
        run_status = "cancelled"

    return RunResponse(
        id=run_id,
        object="thread.run",
        created_at=int(chat_message.time_sent.timestamp()),
        assistant_id=chat_session.persona_id or 0,
        thread_id=chat_session.id,
        status=run_status,
        started_at=int(chat_message.time_sent.timestamp()),
        completed_at=(
            int(chat_message.time_sent.timestamp()) if chat_message.message else None
        ),
        model=chat_session.current_alternate_model or "default_model",
        instructions="",  # DAnswer doesn't store per-message instructions
        tools=[],  # DAnswer doesn't have a direct equivalent for tools
        file_ids=(
            [file["id"] for file in chat_message.files] if chat_message.files else []
        ),
        metadata=None,  # DAnswer doesn't store metadata for individual messages
    )


@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
def cancel_run(
    thread_id: UUID,
    run_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RunResponse:
    # In DAnswer, we don't have a direct equivalent to cancelling a run
    # We'll simulate it by marking the message as "cancelled"
    chat_message = (
        db_session.query(ChatMessage).filter(ChatMessage.id == run_id).first()
    )
    if not chat_message:
        raise HTTPException(status_code=404, detail="Run not found")

    chat_message.error = "Cancelled"
    db_session.commit()

    return retrieve_run(thread_id, run_id, user, db_session)


@router.get("/threads/{thread_id}/runs")
def list_runs(
    thread_id: UUID,
    limit: int = 20,
    order: Literal["asc", "desc"] = "desc",
    after: Optional[str] = None,
    before: Optional[str] = None,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[RunResponse]:
    # In DAnswer, we'll treat each message in a chat session as a "run"
    chat_messages = get_chat_messages_by_session(
        chat_session_id=thread_id,
        user_id=user.id if user else None,
        db_session=db_session,
    )

    # Apply pagination
    if after:
        chat_messages = [msg for msg in chat_messages if str(msg.id) > after]
    if before:
        chat_messages = [msg for msg in chat_messages if str(msg.id) < before]

    # Apply ordering
    chat_messages = sorted(
        chat_messages, key=lambda msg: msg.time_sent, reverse=(order == "desc")
    )

    # Apply limit
    chat_messages = chat_messages[:limit]

    return [
        retrieve_run(thread_id, str(msg.id), user, db_session) for msg in chat_messages
    ]


@router.get("/threads/{thread_id}/runs/{run_id}/steps")
def list_run_steps(
    thread_id: UUID,
    run_id: str,
    limit: int = 20,
    order: Literal["asc", "desc"] = "desc",
    after: Optional[str] = None,
    before: Optional[str] = None,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[dict]:  # You may want to create a specific model for run steps
    # DAnswer doesn't have an equivalent to run steps
    # We'll return an empty list to maintain API compatibility
    return []


# Additional helper functions can be added here if needed
