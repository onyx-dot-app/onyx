from onyx.db.enums import ValidatorType
from onyx.db.models import Persona, Validator
from onyx.server.features.guardrails.validators import (
    mask_pii,
    unmask_pii,
    mask_banned_words,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ValidatorManager:
    """Управляет валидацией сообщений через подключенные к ассистенту валидаторы.

    Обеспечивает последовательное применение валидаторов к входящим сообщениям
    пользователя и исходящим ответам LLM. Поддерживает передачу контекста между
    валидациями (например, маппинг PII данных для маскирования/демаскирования).
    """

    def __init__(self, persona: Persona):
        self.persona = persona
        self._validators = persona.validators
        self._context = {}

    def validate_message(self, message: str, direction: str) -> str:
        """Применяет цепочку валидаторов к сообщению в указанном направлении.

        Валидаторы применяются последовательно, каждый получает результат
        предыдущего. В случае ошибки в отдельном валидаторе цепочка не прерывается,
        а сообщение сохраняет последнее успешное состояние.
        """

        if not self._validators or not message or not message.strip():
            return message

        validated_message = message

        for validator in self._validators:
            try:

                validated_message = self._apply_validator(
                    validator=validator,
                    message=validated_message,
                    config=validator.config,
                    direction=direction,
                )

            except Exception as e:
                logger.error(
                    "Ошибка при выполнении валидатора (name: %s, ID: %s): %s",
                    validator.name, validator.id, repr(e)
                )

        return validated_message

    def _apply_validator(
        self,
        validator: Validator,
        message: str,
        config: dict,
        direction: str
    ):
        """Внутренний метод применения конкретного валидатора.

        В зависимости от направления (input/output) и типа валидатора выполняет
        соответствующую логику обработки сообщения. Для PII-валидаторов поддерживает
        маскирование входящих данных и демаскирование исходящих с сохранением контекста.
        """

        if direction == "input":

            # Маскирование данных
            if validator.validator_type == ValidatorType.DETECT_PII:
                masked_message, mapping = mask_pii(
                    text=message, config=config
                )
                self._context[validator.validator_type] = mapping

                logger.info(
                    "\nDETECT_PII | %s-валидация | Маскирование перс. данных | Результат:\n%s",
                    direction, masked_message,
                )
                return masked_message

            # Классификация и перенаправление запросов, не относящихся к заданным темам
            # Защита от манипулирования LLM (Jailbreaking)

        elif direction == "output":

            # Демаскирование данных
            if validator.validator_type == ValidatorType.DETECT_PII:
                unmasked_message = unmask_pii(
                    llm_response=message, mapping=self._context[validator.validator_type]
                )
                del self._context[validator.validator_type]

                logger.info(
                    "\nDETECT_PII | %s-валидация | Демаскирование перс. данных | Результат:\n%s",
                    direction, unmasked_message,
                )
                return unmasked_message

            # Фильтрация запрещенных слов
            elif validator.validator_type == ValidatorType.BAN_LIST:
                masked_message = mask_banned_words(
                    text=message, config=config
                )

                logger.info(
                    "\nBAN_LIST | %s-валидация | Маскирование запретных слов | Результат:\n%s",
                    direction, masked_message,
                )
                return masked_message

            # Валидация JSON-структуры
            # Проверка ответов на токсичность
            # Проверка длины ответа
            # Фильтрация запрещенных слов
            # Проверка на соответствие определенному стилю
            # Проверка на наличие ключевых сущностей в ответе
            # Проверка галлюцинаций в выводе модели

        return message


if __name__=="__main__":
    from onyx.server.features.guardrails.init_validators import initialize_presidio_analyzer
    initialize_presidio_analyzer()

    validator_1 = Validator(
        id=1,
        name="Перс данные",
        validator_type="DETECT_PII",
        config={"pii_entities": ["EMAIL_ADDRESS", "RUS_PHONE_NUMBER"]}
    )
    validator_2 = Validator(
        id=2,
        name="Запретные слова",
        validator_type="BAN_LIST",
        config={"banned_words": ["запиши"]}
    )
    persona = Persona(
        validators=[
            validator_1,
            validator_2,
        ],
    )
    message = "Напиши мне на почту test@gmail.com и запиши мой номер 8 800 555 3555"
    print(f"Исходное сообщение: {message}")

    validator_manager = ValidatorManager(persona=persona)
    masked_message = validator_manager.validate_message(message=message, direction="input")
    print(f"Маскированное сообщение: {masked_message}")

    unmasked_message = validator_manager.validate_message(message=masked_message, direction="output")
    print(f"Демаскированное сообщение: {unmasked_message}")
