from presidio_analyzer import Pattern, PatternRecognizer


def create_custom_recognizers() -> list[PatternRecognizer]:
    """Создаем кастомные распознаватели для русского языка
    для валидатора DETECT_PII маскирование/демаскирование данных
    """

    # Российские номера телефонов
    # (\+7|8)          # Начинается с "+7" или "8"
    # [-\s]?           # Необязательный дефис или пробел
    # \(?              # Необязательная открывающая скобка
    # \d{3}            # Ровно 3 цифры (код)
    # \)?              # Необязательная закрывающая скобка
    # [-\s]?           # Необязательный дефис или пробел
    # \d{3}            # Ровно 3 цифры
    # [-\s]?           # Необязательный дефис или пробел
    # \d{2}            # Ровно 2 цифры
    # [-\s]?           # Необязательный дефис или пробел
    # \d{2}            # Ровно 2 цифры
    russian_phone_recognizer = PatternRecognizer(
        supported_entity="RUS_PHONE_NUMBER",
        patterns=[
            Pattern(
                name="russian_phone",
                regex=r"(\+7|8)[-\s]?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}",
                score=0.9
            )
        ],
        supported_language="en"
    )

    return [
        russian_phone_recognizer,
    ]
