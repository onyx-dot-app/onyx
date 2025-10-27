import json
import re

from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


def llm_analyzer(
    llm: LLM, text: str, sensitive_topics: list[str]
) -> list[str] | None:
    """Анализирует текст ответа от LLM на используемые темы"""

    prompt = f"""
    Ты - классификатор текста. Проанализируй текст и определи, присутствуют ли в нем указанные темы.

    ТЕКСТ ДЛЯ АНАЛИЗА: "{text}"

    ТЕМЫ ДЛЯ ПРОВЕРКИ: {sensitive_topics}

    ИНСТРУКЦИЯ:
    - Верни JSON объект с полем "topics_present", содержащим список найденных тем
    - Если тем не найдено, верни пустой список
    - Отвечай ТОЛЬКО в формате JSON, без дополнительного текста

    ПРИМЕР ОТВЕТА:
    "topics_present": ["война", "политика"]

    ТВОЙ ОТВЕТ:
    """

    try:

        response = llm.invoke(prompt=prompt)
        result_text = response.content.strip()

        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            result = json.loads(json_str)
            found_topics = result.get("topics_present", [])
            return found_topics

        logger.warning("В ответе LLM не найден JSON при валидации SENSITIVE_TOPIC")
        return []

    except Exception as e:
        logger.error(
            "Ошибка при анализе запретных тем: %s", repr(e)
        )
        return []


def detect_sensitive_topic(
    llm: LLM,
    text: str,
    config: dict,
) -> tuple[str, bool]:
    """Распознавание запретных тем"""

    sensitive_topics = config.get("sensitive_topics")

    if not sensitive_topics:
        return text, False

    found_topics = llm_analyzer(
        llm=llm, text=text, sensitive_topics=sensitive_topics
    )

    if not found_topics:
       return text, False

    rejection_message = config.get("rejection_message")

    if not rejection_message or not rejection_message.strip():
        rejection_message = "К сожалению, я не могу ответить на ваш запрос."

    return rejection_message, True
