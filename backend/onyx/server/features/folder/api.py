from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.chat import get_chat_session_by_id
from onyx.db.engine import get_session
from onyx.db.folder import (
    add_chat_to_folder,
    create_folder,
    delete_folder,
    get_user_folders,
    remove_chat_from_folder,
    rename_folder,
    update_folder_display_priority,
)
from onyx.db.models import User
from onyx.server.features.folder.models import (
    DeleteFolderOptions,
    FolderChatSessionRequest,
    FolderCreationRequest,
    FolderUpdateRequest,
    GetUserFoldersResponse,
    UserFolderSnapshot,
)
from onyx.server.models import DisplayPriorityRequest
from onyx.server.query_and_chat.models import ChatSessionDetails

router = APIRouter(prefix="/folder")


@router.get("")
def get_folders(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> GetUserFoldersResponse:
    folders = get_user_folders(
        user_id=user.id if user else None,
        db_session=db_session,
    )
    folders.sort()
    return GetUserFoldersResponse(
        folders=[
            UserFolderSnapshot(
                folder_id=folder.id,
                folder_name=folder.name,
                display_priority=folder.display_priority,
                chat_sessions=[
                    ChatSessionDetails(
                        id=chat_session.id,
                        name=chat_session.description,
                        persona_id=chat_session.persona_id,
                        time_created=chat_session.time_created.isoformat(),
                        time_updated=chat_session.time_updated.isoformat(),
                        shared_status=chat_session.shared_status,
                        folder_id=folder.id,
                    )
                    for chat_session in folder.chat_sessions
                    if not chat_session.deleted
                ],
            )
            for folder in folders
        ]
    )


@router.put("/reorder")
def put_folder_display_priority(
    display_priority_request: DisplayPriorityRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_folder_display_priority(
        user_id=user.id if user else None,
        display_priority_map=display_priority_request.display_priority_map,
        db_session=db_session,
    )


@router.post("")
def create_folder_endpoint(
    request: FolderCreationRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> int:
    return create_folder(
        user_id=user.id if user else None,
        folder_name=request.folder_name,
        db_session=db_session,
    )


@router.patch("/{folder_id}")
def patch_folder_endpoint(
    request: FolderUpdateRequest,
    folder_id: int = Path(..., description="The ID of the folder to rename"),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        rename_folder(
            user_id=user.id if user else None,
            folder_id=folder_id,
            folder_name=request.folder_name,
            db_session=db_session,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{folder_id}")
def delete_folder_endpoint(
    request: DeleteFolderOptions,
    folder_id: int = Path(..., description="The ID of the folder to delete"),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None
    try:
        delete_folder(
            user_id=user_id,
            folder_id=folder_id,
            including_chats=request.including_chats,
            db_session=db_session,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{folder_id}/add-chat-session")
def add_chat_to_folder_endpoint(
    request: FolderChatSessionRequest,
    folder_id: int = Path(
        ..., description="The ID of the folder in which to add the chat session"
    ),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=request.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
        add_chat_to_folder(
            user_id=user.id if user else None,
            folder_id=folder_id,
            chat_session=chat_session,
            db_session=db_session,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{folder_id}/remove-chat-session/")
def remove_chat_from_folder_endpoint(
    request: FolderChatSessionRequest,
    folder_id: int = Path(
        ..., description="The ID of the folder from which to remove the chat session"
    ),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=request.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
        remove_chat_from_folder(
            user_id=user_id,
            folder_id=folder_id,
            chat_session=chat_session,
            db_session=db_session,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
