from onyx.db.enums import ValidatorType
from onyx.db.models import Persona, Validator
from onyx.server.features.guardrails.validators.detect_pii import validate_detect_pii
from onyx.utils.logger import setup_logger

logger = setup_logger()


def validate_message_with_persona_validators(
    persona: Persona,
    message: str,
) -> str:
    """Основная функция валидации сообщения через валидаторы ассистента.

    Args:
        persona: Объект ассистента, по которому будут извлекаться подключённые валидаторы
        message: Входное сообщение для валидации
    Returns:
        str: Валидированное сообщение
    """

    # Если к ассистенту не подключены валидаторы - возвращаем исходное сообщение
    if not persona.validators:
        return message

    # Применяем валидаторы последовательно
    validated_message = message  # Начинаем с исходного сообщения

    for validator in persona.validators:
        # Каждый следующий валидатор получает результат предыдущего
        validated_message = apply_validator(
            validator=validator,
            message=validated_message,
        )

    return validated_message


def apply_validator(validator: Validator, message: str) -> str:
    """Применяет конкретный валидатор к сообщению в зависимости от типа"""

    try:
        config = validator.config or {}

        # Выбираем функцию валидации по типу валидатора
        if validator.validator_type == ValidatorType.DETECT_PII:
            return validate_detect_pii(
                message=message,
                config=config,
            )
        else:
            logger.warning(f"Unknown validator type: {validator.validator_type}")
            return message

    except Exception as e:
        logger.error(f"Error applying validator {validator.name}: {e}")
        return message  # в случае ошибки возвращаем исходное сообщение


if __name__=="__main__":
    validator_1 = Validator(validator_type="DETECT_PII", config={"pii_entities": ["EMAIL_ADDRESS"]})
    persona = Persona(
        validators=[
            validator_1,
        ],
    )
    message = "Напиши мне на почту test@gmail.com"
    validated_message = validate_message_with_persona_validators(persona=persona, message=message)
    print(validated_message)
