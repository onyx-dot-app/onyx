from guardrails.hub import DetectPII
from guardrails import Guard, settings

from onyx.utils.logger import setup_logger

logger = setup_logger()


def validate_detect_pii(
        message: str, config: dict, on_fail: str = "fix"
) -> str:
    """Выполняет обнаружение персональных данных в тексте.

    Функция выполняет анализ переданного текста на наличие указанных типов
    персональных данных и возвращает либо текст с маскированными участками,
    либо исходный текст в зависимости от результата обнаружения.

    Args:
        message: Текст для анализа на наличие персональных данных
        config: Настройки валидатора, например, {"pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER"]}

    Returns:
        validated_message: Текст с маскированными данными или исходный текст, если PII не обнаружены

    Examples:
        input: Напиши мне на почту test@gmail.com и запиши мой номер +79611234567
        output: Напиши мне на почту <EMAIL_ADDRESS> и запиши мой номер <PHONE_NUMBER>
    """
    try:
        guard = Guard().use(
            validator=DetectPII,
            pii_entities=config["pii_entities"],
            on_fail=on_fail  # автоматически маскирует найденные PII
        )

        result = guard.validate(message)
        validated_message: str = result.validated_output

        return validated_message
    except Exception as e:
        logger.debug(f"Error during PII validation: %s", str(e))
        return message


if __name__=="__main__":
    print("Метрики:", settings.rc.enable_metrics)
    print("Удаленное выполнение:", getattr(settings.rc, "enable_remote_inferencing", None))

    message = "Напиши мне на почту test@gmail.com и запиши мой номер +79611234567"
    config = {"pii_entities": ["EMAIL_ADDRESS"]}

    validated_output = validate_detect_pii(message=message, config=config)
    print(validated_output)
