from presidio_analyzer import PatternRecognizer
from presidio_anonymizer import OperatorConfig

from onyx.server.features.guardrails.init_validators import _anonymizer


def mask_banned_words(text: str, config: dict,) -> str:
    """ Маскирует запретные слова символом '*' """

    banned_words = config.get("banned_words")

    if not banned_words:
        return text

    # Создаём временный распознаватель
    recognizer = PatternRecognizer(
        supported_entity="BAN_WORD",
        deny_list=banned_words
    )

    # Создаём оператор
    operators = {
        "BAN_WORD": OperatorConfig(
            operator_name="mask",
            params={
                    "type": "mask",
                    "masking_char": "*",
                    "chars_to_mask": 30,
                    "from_end": False,
            },
        )
    }

    # Анализируем текст
    analyzer_results = recognizer.analyze(
        text=text,
        entities=["BAN_WORD"],
    )

    # Маскируем текст с запретными словами
    anonymized_result = _anonymizer.anonymize(
        text=text,
        analyzer_results=analyzer_results,
        operators=operators
    )

    return anonymized_result.text


if __name__=="__main__":
    config = {
        "banned_words": [
            "демонстрация",
            "запретных",
        ]
    }

    message = "Демонстрация работы валидатора запретных слов"
    print(f"Исходное сообщение: {message}")

    masked_message = mask_banned_words(text=message, config=config)
    print(f"Маскированное сообщение: {masked_message}")
