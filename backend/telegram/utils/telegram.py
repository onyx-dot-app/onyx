import json
from typing import Any

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()


def request_answer_from_smartsearch(message: str, token: str, persona_id: int | None = None,
                                    chat_session_id: int | None = None,
                                    llm_model: dict | None = None,
                                    parent_message_id: int | None = None,
                                    prompt_id: int | None = None,
                                    files: list | None = None) -> dict[str, int | Any] | None:

    """
    llm_model: dict. Example { "model_provider": "Gigachat", "model_version": "GigaChat-preview" }
    """
    if chat_session_id is None and persona_id is None:
        raise ValueError("Needs to provide chat_session_id or persona_id")
    if chat_session_id is None:
        request = requests.post(f"http://api_server:8080/telegram/create-chat-session?token={token}",
                                json={"persona_id": persona_id, "description": ""})
        response = request.json()
        chat_session_id = response['chat_session_id']
    file_descriptors = []
    if files:
        with requests.post(f"http://api_server:8080/telegram/file?token={token}",
                           files={"files": files}) as resp:
            if resp.status_code == 200:
                result = resp.json()
                file_descriptors.append({
                    "id": result['files'][0]['id'],
                    "type": result['files'][0]['type'],
                    "name": result['files'][0]['name']
                })
    with requests.post(f"http://api_server:8080/telegram/send-message?token={token}",
                       json={"chat_session_id": chat_session_id,
                             "file_descriptors": file_descriptors,
                             "llm_override": llm_model,
                             "message": message,
                             "parent_message_id": parent_message_id,
                             "prompt_id": prompt_id,
                             "prompt_override": None,
                             "retrieval_options": {
                                 "run_search": "auto",
                                 "real_time": True,
                                 "filters": {
                                     "source_type": None,
                                     "document_set": None,
                                     "time_cutoff": None,
                                     "tags": []
                                 }
                             },
                             "search_doc_ids": None},
                       stream=True) as resp:
        for line in resp.iter_lines():
            if line:
                js = json.loads(line)
                if js.get('message'):
                    return {"message": js['message'], "chat_session_id": chat_session_id, "parent_message_id":
                            js['message_id']}
