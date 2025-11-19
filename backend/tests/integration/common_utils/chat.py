import requests

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User


def test_create_chat_session_and_send_messages() -> None:
    # Create a test user
    with get_session_with_current_tenant() as db_session:
        test_user = User(email="test@example.com", hashed_password="dummy_hash")
        db_session.add(test_user)
        db_session.commit()

    base_url = "http://localhost:8080"  # Adjust this to your API's base URL
    headers = {"Authorization": f"Bearer {test_user.id}"}

    # Create a new chat session
    create_session_response = requests.post(
        f"{base_url}/chat/create-chat-session",
        json={
            "description": "Test Chat",
            "persona_id": 1,
        },  # Assuming persona_id 1 exists
        headers=headers,
    )
    assert create_session_response.status_code == 200
    chat_session_id = create_session_response.json()["chat_session_id"]

    # Send first message
    first_message = "Hello, this is a test message."
    send_message_response = requests.post(
        f"{base_url}/chat/send-message",
        json={
            "chat_session_id": chat_session_id,
            "message": first_message,
            "retrieval_options": {"top_k": 3},
            "stream_response": False,
        },
        headers=headers,
    )
    assert send_message_response.status_code == 200

    # Send second message
    second_message = "Can you provide more information?"
    send_message_response = requests.post(
        f"{base_url}/chat/send-message",
        json={
            "chat_session_id": chat_session_id,
            "message": second_message,
            "retrieval_options": {"top_k": 3},
            "stream_response": False,
        },
        headers=headers,
    )
    assert send_message_response.status_code == 200

    # Verify chat session details
    get_session_response = requests.get(
        f"{base_url}/chat/get-chat-session/{chat_session_id}", headers=headers
    )
    assert get_session_response.status_code == 200
    session_details = get_session_response.json()
    assert session_details["chat_session_id"] == chat_session_id
    assert session_details["description"] == "Test Chat"
    assert len(session_details["messages"]) == 4  # 2 user messages + 2 AI responses
