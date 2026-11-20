"""Print a streamed answer from the Onyx chat API."""

import argparse
import json
import os

import requests


def process_question(onyx_url: str, question: str, api_key: str | None) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with requests.post(
        f"{onyx_url.rstrip('/')}/api/chat/send-chat-message",
        headers=headers,
        json={"message": question, "chat_session_info": {}, "protocol_version": 2},
        stream=True,
        timeout=(10, 120),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event["method"] == "_onyx/error":
                raise RuntimeError(event["params"]["packet"]["error"])
            if event["method"] == "session/update":
                update = event["params"]["update"]
                if update["sessionUpdate"] == "agent_message_chunk":
                    print(update["content"]["text"], end="", flush=True)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onyx-url", default="http://localhost:80")
    parser.add_argument("--test-question", default="What is Onyx?")
    args = parser.parse_args()
    process_question(
        args.onyx_url, args.test_question, os.environ.get("DANSWER_API_KEY")
    )
