# This file is used to demonstrate how to use the backend APIs directly
# In this case, the equivalent of asking a question in Onyx Chat in a new chat session
import argparse
import json
import os

import requests


def create_new_chat_session(onyx_url: str, api_key: str | None) -> int:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    session_endpoint = onyx_url + "/api/chat/create-chat-session"

    response = requests.post(
        session_endpoint,
        headers=headers,
        json={"persona_id": 0},  # Global default Persona/Assistant ID
    )
    response.raise_for_status()

    new_session_id = response.json()["chat_session_id"]
    return new_session_id


def process_question(onyx_url: str, question: str, api_key: str | None) -> None:
    message_endpoint = onyx_url + "/api/chat/send-message"

    chat_session_id = create_new_chat_session(onyx_url, api_key)

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    data = {
        "message": question,
        "chat_session_id": chat_session_id,
        "parent_message_id": None,
        "file_descriptors": [],
        # Default Question Answer prompt
        "prompt_id": 0,
        # Not specifying any specific docs to chat to, we want to run a search
        "search_doc_ids": None,
        "retrieval_options": {
            "run_search": "always",
            "real_time": True,
            "enable_auto_detect_filters": False,
            # No filters applied, check all sources, document-sets, time ranges, etc.
            "filters": {},
        },
    }

    with requests.post(message_endpoint, headers=headers, json=data) as response:
        response.raise_for_status()

        for packet in response.iter_lines():
            response_text = json.loads(packet.decode())
            # Can also check "top_documents" to capture the streamed search results
            # that include the highest matching documents to the query
            # or check "message_id" to get the message_id used as parent_message_id
            # to create follow-up messages
            new_token = response_text.get("answer_piece")

            if new_token:
                print(new_token, end="", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample API Usage")
    parser.add_argument(
        "--onyx-url",
        type=str,
        default="http://localhost:80",
        help="Onyx URL, should point to Onyx nginx.",
    )
    parser.add_argument(
        "--test-question",
        type=str,
        default="What is Onyx?",
        help="Test question for new Chat Session.",
    )

    # Not needed if Auth is disabled
    # Or for Onyx MIT API key must be replaced with session cookie
    api_key = os.environ.get("DANSWER_API_KEY")

    args = parser.parse_args()
    process_question(
        onyx_url=args.onyx_url, question=args.test_question, api_key=api_key
    )
