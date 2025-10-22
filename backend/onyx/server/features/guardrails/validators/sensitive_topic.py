import json
import re

from guardrails import Guard
from guardrails.hub import SensitiveTopic

from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_llm_callable(llm: LLM):
    """Создает callable функцию для Guardrails"""

    def llm_analyzer(text: str, topics: list[str]) -> list[str] | None:
        """Анализирует текст на темы используя Ollama"""

        prompt = f"""
        Ты - классификатор текста. Проанализируй текст и определи, присутствуют ли в нем указанные темы.

        ТЕКСТ ДЛЯ АНАЛИЗА: "{text}"

        ТЕМЫ ДЛЯ ПРОВЕРКИ: {topics}

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

    return llm_analyzer


def detect_sensitive_topic(
    llm: LLM,
    text: str,
    config: dict,
) -> tuple[str, bool]:
    """Распознавание запретных тем"""

    sensitive_topics = config.get("sensitive_topics")

    if not sensitive_topics:
        return text, False

    llm_callable = create_llm_callable(llm=llm)

    guard = Guard().use(
        SensitiveTopic,
        sensitive_topics=sensitive_topics,
        llm_callable=llm_callable,
        disable_classifier=True,
        disable_llm=False,
        on_fail="exception",
    )

    try:
        guard.validate(text)
    except Exception as e:
        text = "К сожалению, я не могу ответить на ваш запрос."
        return text, True

    return text, False
