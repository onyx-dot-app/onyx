import json
from typing import Any

import requests

from onyx.context.search.enums import OptionalSearchSetting
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
        logger.info(f"Создание новой чат сессии persona_id={persona_id}, prompt_id={prompt_id}")
        request = requests.post(f"http://api_server:8080/telegram/create-chat-session?token={token}",
                                json={"persona_id": persona_id, "description": ""})
        response = request.json()
        chat_session_id = response['chat_session_id']
        logger.info(f"Создана новая чат сессия {chat_session_id}")

    logger.info(f"Использование существующей чат сессии {chat_session_id}")

    file_descriptors = []
    if files:
        logger.info(f"Обработка файлов для загрузки: {len(files)} файл(ов)")
        with requests.post(f"http://api_server:8080/telegram/file?token={token}",
                           files={"files": files}) as resp:
            if resp.status_code == 200:
                result = resp.json()
                file_descriptors.append({
                    "id": result['files'][0]['id'],
                    "type": result['files'][0]['type'],
                    "name": result['files'][0]['name']
                })
                logger.info(f"Файл загружен: id={file_descriptors[0]['id']}, name={file_descriptors[0]['name']}")
            else:
                logger.warning(f"Ошибка загрузки файла: status_code={resp.status_code}")

    with requests.post(f"http://api_server:8080/telegram/send-message?token={token}",
                       json={"chat_session_id": chat_session_id,
                             "file_descriptors": file_descriptors,
                             "llm_override": llm_model,
                             "message": message,
                             "parent_message_id": parent_message_id,
                             "prompt_id": prompt_id,
                             "prompt_override": None,
                             "retrieval_options": {

                                 # ALWAYS - принудительный поиск по документам при каждом запросе.
                                 # TODO Пересмотреть логику поиска по документам, чтобы он
                                 # TODO производился только у ассистентов, к которым
                                 # TODO подключена база знаний.
                                 # К ассистенту 'LLM' ничего не подключено, тут будет уместно OptionalSearchSetting.NEVER
                                 "run_search": OptionalSearchSetting.ALWAYS,

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
                    logger.info(
                        f"Получен ответ от SmartSearch для chat_session_id={chat_session_id}, "
                        f"message_id={js['message_id']}"
                    )
                    return {"message": js['message'], "chat_session_id": chat_session_id, "parent_message_id":
                            js['message_id']}
