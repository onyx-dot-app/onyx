from onyx.db.enums import ValidatorType
from onyx.db.models import Persona, Validator
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.server.features.guardrails.validators import (
    mask_pii,
    unmask_pii,
    validate_banned_words,
    detect_sensitive_topic,
    validate_text_style,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


class ValidatorManager:
    """Управляет валидацией сообщений через подключенные к ассистенту валидаторы.

    Обеспечивает последовательное применение валидаторов к входящим сообщениям
    пользователя и исходящим ответам LLM. Поддерживает передачу контекста между
    валидациями (например, маппинг PII данных для маскирования/демаскирования).
    """

    # Заданный порядок валидации по направлениям
    _VALIDATION_ORDER = {
        "input": [
            ValidatorType.DETECT_PII,  # 1. Маскирование данных
        ],
        "output": [
            ValidatorType.SENSITIVE_TOPIC,  # 1. Запретные темы
            ValidatorType.DETECT_PII,  # 2. Демаскирование данных
            ValidatorType.TEXT_STYLE,  # 3. Валидация текста определенному стилю
            ValidatorType.BAN_LIST,  # 4. Запретные слова
        ]
    }

    def __init__(self, persona: Persona):
        self.persona = persona
        self._validators = persona.validators
        self._context = {}
        self._is_blocked = False

    def _get_ordered_validators(self, direction: str) -> list[Validator]:
        """Возвращает валидаторы в правильном порядке,
        исходя из заданного направления валидации (input, output)
        """

        order = self._VALIDATION_ORDER.get(direction, [])

        validator_by_type = {v.validator_type: v for v in self._validators}

        ordered = []

        for validator_type in order:
            if validator_type in validator_by_type:
                ordered.append(validator_by_type[validator_type])

        return ordered

    def validate_message(self, message: str, direction: str) -> str:
        """Применяет цепочку валидаторов к сообщению в указанном направлении.

        Валидаторы применяются последовательно, каждый получает результат
        предыдущего. В случае ошибки в отдельном валидаторе цепочка не прерывается,
        а сообщение сохраняет последнее успешное состояние.
        """

        if not self._validators or not message or not message.strip():
            return message

        # Сортируем валидаторы согласно порядку
        ordered_validators = self._get_ordered_validators(direction)

        validated_message = message

        for validator in ordered_validators:
            try:

                if self._is_blocked:
                    logger.info("Валидация заблокирована")
                    break

                validated_message = self._apply_validator(
                    validator=validator,
                    message=validated_message,
                    config=validator.config,
                    direction=direction,
                )

                logger.info(
                    "\n%s | %s-валидация | %s | Результат:\n%s",
                    validator.validator_type,
                    direction,
                    validator.name,
                    validated_message,
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

                return unmasked_message

            # Фильтрация запрещенных слов
            elif validator.validator_type == ValidatorType.BAN_LIST:
                masked_message = validate_banned_words(
                    text=message, config=config
                )

                return masked_message

            # Валидация запретных и чувствительных тем
            elif validator.validator_type == ValidatorType.SENSITIVE_TOPIC:
                llm = self._get_llm(validator=validator)
                if not llm:
                    return message

                validated_message, is_blocked = detect_sensitive_topic(
                    llm=llm, text=message, config=config
                )
                self._is_blocked = is_blocked

                return validated_message

            # Проверка на соответствие определенному стилю
            elif validator.validator_type == ValidatorType.TEXT_STYLE:
                llm = self._get_llm(validator=validator)
                if not llm:
                    return message

                validated_message = validate_text_style(
                    llm=llm, text=message, config=config
                )

                return validated_message

            # Валидация JSON-структуры
            # Проверка ответов на токсичность
            # Проверка длины ответа
            # Проверка на наличие ключевых сущностей в ответе
            # Проверка галлюцинаций в выводе модели

        return message

    @staticmethod
    def _get_llm(validator: Validator) -> LLM | None:
        llm_provider = validator.llm_provider

        if llm_provider:
            llm = llm_from_provider(
                model_name=llm_provider.default_model_name,
                llm_provider=llm_provider,
            )
            return llm

        logger.warning(
            "К валидатору %s не подключен LLM-провайдер",
            validator.validator_type,
        )
        return None


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
