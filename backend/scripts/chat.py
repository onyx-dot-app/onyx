import argparse
import logging
import random
from datetime import datetime
from datetime import timedelta
from logging import getLogger

from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import ChatSession

# def test_create_chat_session_and_send_messages(db_session: Session) -> None:
#     # Create a test user
#     test_user = User(email="test@example.com", hashed_password="dummy_hash")
#     db_session.add(test_user)
#     db_session.commit()
#     base_url = "http://localhost:8080"  # Adjust this to your API's base URL
#     headers = {"Authorization": f"Bearer {test_user.id}"}
#     # Create a new chat session
#     create_session_response = requests.post(
#         f"{base_url}/chat/create-chat-session",
#         json={
#             "description": "Test Chat",
#             "persona_id": 1,
#         },  # Assuming persona_id 1 exists
#         headers=headers,
#     )
#     assert create_session_response.status_code == 200
#     chat_session_id = create_session_response.json()["chat_session_id"]
#     # Send first message
#     first_message = "Hello, this is a test message."
#     send_message_response = requests.post(
#         f"{base_url}/chat/send-message",
#         json={
#             "chat_session_id": chat_session_id,
#             "message": first_message,
#             "prompt_id": None,
#             "retrieval_options": {"top_k": 3},
#             "stream_response": False,
#         },
#         headers=headers,
#     )
#     assert send_message_response.status_code == 200
#     # Send second message
#     second_message = "Can you provide more information?"
#     send_message_response = requests.post(
#         f"{base_url}/chat/send-message",
#         json={
#             "chat_session_id": chat_session_id,
#             "message": second_message,
#             "prompt_id": None,
#             "retrieval_options": {"top_k": 3},
#             "stream_response": False,
#         },
#         headers=headers,
#     )
#     assert send_message_response.status_code == 200
#     # Verify chat session details
#     get_session_response = requests.get(
#         f"{base_url}/chat/get-chat-session/{chat_session_id}", headers=headers
#     )
#     assert get_session_response.status_code == 200
#     session_details = get_session_response.json()
#     assert session_details["chat_session_id"] == chat_session_id
#     assert session_details["description"] == "Test Chat"
#     assert len(session_details["messages"]) == 4  # 2 user messages + 2 AI responses
# This file is used to demonstrate how to use the backend APIs directly
# to query out feedback for all messages

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)


def go_main() -> None:
    with get_session_with_current_tenant() as db_session:
        for y in range(0, 32):
            chat_session: ChatSession = create_chat_session(
                db_session, f"pytest_session_{y}", None, None
            )

            root_message = get_or_create_root_message(chat_session.id, db_session)

            for x in range(0, 32):
                create_new_chat_message(
                    chat_session.id,
                    root_message,
                    f"pytest_message_{x}",
                    None,
                    0,
                    MessageType.USER,
                    db_session,
                )

        # randomize all message times
        rows = db_session.query(ChatSession).all()
        for row in rows:
            row.time_created = datetime.utcnow() - timedelta(days=random.randint(0, 90))
            row.time_updated = row.time_created + timedelta(
                minutes=random.randint(0, 10)
            )
            db_session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample API Usage - Seed chat history")

    args = parser.parse_args()
    go_main()
