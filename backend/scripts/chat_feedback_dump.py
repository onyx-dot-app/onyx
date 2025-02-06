# This file is used to demonstrate how to use the backend APIs directly
# to query out feedback for all messages
import argparse
import logging
from logging import getLogger
from typing import Any
from uuid import UUID

import requests

from ee.onyx.server.query_history.api import ChatSessionSnapshot
from onyx.server.manage.models import AllUsersResponse
from onyx.server.query_and_chat.models import ChatSessionsResponse

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)

# uncomment the following pydantic models if you need the script to be independent
# from pydantic import BaseModel
# from datetime import datetime
# from enum import Enum

# class UserRole(str, Enum):
#     """
#     User roles
#     - Basic can't perform any admin actions
#     - Admin can perform all admin actions
#     - Curator can perform admin actions for
#         groups they are curators of
#     - Global Curator can perform admin actions
#         for all groups they are a member of
#     """

#     BASIC = "basic"
#     ADMIN = "admin"
#     CURATOR = "curator"
#     GLOBAL_CURATOR = "global_curator"


# class FullUserSnapshot(BaseModel):
#     id: UUID
#     email: str
#     role: UserRole
#     is_active: bool


# class InvitedUserSnapshot(BaseModel):
#     email: str


# class AllUsersResponse(BaseModel):
#     accepted: list[FullUserSnapshot]
#     invited: list[InvitedUserSnapshot]
#     accepted_pages: int
#     invited_pages: int


# class ChatSessionSharedStatus(str, Enum):
#     PUBLIC = "public"
#     PRIVATE = "private"


# class ChatSessionDetails(BaseModel):
#     id: UUID
#     name: str
#     persona_id: int | None = None
#     time_created: str
#     shared_status: ChatSessionSharedStatus
#     folder_id: int | None = None
#     current_alternate_model: str | None = None


# class ChatSessionsResponse(BaseModel):
#     sessions: list[ChatSessionDetails]


# class SessionType(str, Enum):
#     CHAT = "Chat"
#     SEARCH = "Search"
#     SLACK = "Slack"


# class AbridgedSearchDoc(BaseModel):
#     """A subset of the info present in `SearchDoc`"""

#     document_id: str
#     semantic_identifier: str
#     link: str | None


# class QAFeedbackType(str, Enum):
#     LIKE = "like"  # User likes the answer, used for metrics
#     DISLIKE = "dislike"  # User dislikes the answer, used for metrics


# class MessageType(str, Enum):
#     # Using OpenAI standards, Langchain equivalent shown in comment
#     # System message is always constructed on the fly, not saved
#     SYSTEM = "system"  # SystemMessage
#     USER = "user"  # HumanMessage
#     ASSISTANT = "assistant"  # AIMessage


# class MessageSnapshot(BaseModel):
#     id: int
#     message: str
#     message_type: MessageType
#     documents: list[AbridgedSearchDoc]
#     feedback_type: QAFeedbackType | None
#     feedback_text: str | None
#     time_created: datetime


# class ChatSessionSnapshot(BaseModel):
#     id: UUID
#     user_email: str
#     name: str | None
#     messages: list[MessageSnapshot]
#     persona_name: str | None
#     time_created: datetime
#     flow_type: SessionType


def create_new_chat_session(onyx_url: str, api_key: str | None) -> int:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    session_endpoint = onyx_url + "/api/chat/create-chat-session"

    response = requests.get(session_endpoint, headers=headers)
    response.raise_for_status()

    new_session_id = response.json()["chat_session_id"]
    return new_session_id


def manage_users(onyx_url: str, headers: dict[str, str] | None) -> AllUsersResponse:
    endpoint = onyx_url + "/manage/users"

    response = requests.get(
        endpoint,
        headers=headers,
    )
    response.raise_for_status()

    all_users = AllUsersResponse(**response.json())
    return all_users


def get_chat_sessions(
    onyx_url: str, headers: dict[str, str] | None, user_id: UUID
) -> ChatSessionsResponse:
    endpoint = onyx_url + "/admin/chat-sessions"

    params: dict[str, Any] = {"user_id": user_id}
    response = requests.get(
        endpoint,
        params=params,
        headers=headers,
    )
    response.raise_for_status()

    sessions = ChatSessionsResponse(**response.json())
    return sessions


def get_session_history(
    onyx_url: str, headers: dict[str, str] | None, session_id: UUID
) -> ChatSessionSnapshot:
    endpoint = onyx_url + f"/admin/chat-session-history/{session_id}"

    response = requests.get(
        endpoint,
        headers=headers,
    )
    response.raise_for_status()

    sessions = ChatSessionSnapshot(**response.json())
    return sessions


def process_all_chat_feedback(onyx_url: str, api_key: str | None) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    all_users = manage_users(onyx_url, headers)
    if not all_users:
        raise RuntimeError("manage_users returned None")

    logger.info(f"Accepted users: {len(all_users.accepted)}")

    user_ids: list[UUID] = [user.id for user in all_users.accepted]

    for user_id in user_ids:
        r_sessions = get_chat_sessions(onyx_url, headers, user_id)
        logger.info(f"user={user_id} num_sessions={len(r_sessions.sessions)}")
        for session in r_sessions.sessions:
            s: ChatSessionSnapshot
            try:
                s = get_session_history(onyx_url, headers, session.id)
            except requests.exceptions.HTTPError:
                logger.exception("get_session_history failed.")

            for m in s.messages:
                logger.info(
                    f"user={user_id} "
                    f"session={session.id} "
                    f"message={m.message} "
                    f"feedback_type={m.feedback_type} "
                    f"feedback_text={m.feedback_text}"
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample API Usage - Chat Feedback")
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8080",
        help="Onyx URL, should point to Onyx nginx.",
    )

    # Not needed if Auth is disabled?
    # Or for Onyx MIT Edition API key must be replaced with session cookie
    parser.add_argument(
        "--api-key",
        type=str,
        help="Onyx Admin Level API key",
    )

    args = parser.parse_args()
    process_all_chat_feedback(onyx_url=args.url, api_key=args.api_key)
