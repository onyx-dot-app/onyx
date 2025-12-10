from presidio_analyzer import (
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerResult,
)
import spacy

from onyx.utils.logger import setup_logger

logger = setup_logger()


class BaseRusRecognizer(EntityRecognizer):
    """Базовый класс для распознавателей"""

    _nlp = None

    @classmethod
    def initialize(cls):
        if cls._nlp is None:
            try:
                cls._nlp = spacy.load("ru_core_news_sm")
                logger.info("ru_core_news_sm загружена")
            except Exception as e:
                logger.error(
                    "Ошибка при загрузке ru_core_news_sm: %s", repr(e)
                )
                raise

    def __init__(self, supported_entities: list, name: str):
        self.__class__.initialize()
        super().__init__(
            supported_entities=supported_entities,
            name=name
        )

    def _process_text(self, text: str):
        try:
            return self._nlp(text)
        except Exception as e:
            logger.error(
                "Ошибка при обнаружении ФИО или Локации: %s",
                repr(e),
            )
            return None


class RusPersonRecognizer(BaseRusRecognizer):
    """Распознаватель ФИО для Presidio"""

    def __init__(self):
        super().__init__(
            supported_entities=["RUS_PERSON"],
            name="RusPersonRecognizer"
        )

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):
        results = []
        doc = self._process_text(text)

        if doc is None:
            return results

        for ent in doc.ents:
            if ent.label_ == "PER":
                results.append(
                    RecognizerResult(
                        entity_type="RUS_PERSON",
                        start=ent.start_char,
                        end=ent.end_char,
                        score=0.9,
                    )
                )

        return results


class RusLocationRecognizer(BaseRusRecognizer):
    """Распознаватель локаций для Presidio"""

    def __init__(self):
        super().__init__(
            supported_entities=["RUS_LOCATION"],
            name="RusLocationRecognizer"
        )

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):
        results = []
        doc = self._process_text(text)

        if doc is None:
            return results

        for ent in doc.ents:
            if ent.label_ == "LOC":
                results.append(
                    RecognizerResult(
                        entity_type="RUS_LOCATION",
                        start=ent.start_char,
                        end=ent.end_char,
                        score=0.8,
                    )
                )

        return results


def create_custom_recognizers() -> list[PatternRecognizer]:
    """Создаем кастомные распознаватели для русского языка
    для валидатора DETECT_PII маскирование/демаскирование данных
    """

    # Российские номера телефонов
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

    russian_bank_card_recognizer = PatternRecognizer(
        supported_entity="RUS_BANK_CARD",
        patterns=[
            Pattern(
                name="bank_card_mir",
                regex=r"(220[0-4][- ]?\d{4}[- ]?\d{4}[- ]?\d{4})",
                score=0.85
            ),
            Pattern(
                name="bank_card_visa",
                regex=r"(4\d{3}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4})",
                score=0.85
            ),
            Pattern(
                name="bank_card_mastercard",
                regex=r"(5[1-5]\d{2}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4})",
                score=0.85
            )
        ],
        supported_language="en"
    )

    # Российские ИНН
    russian_inn_recognizer = PatternRecognizer(
        supported_entity="RUS_INN",
        patterns=[
            # ИНН физического лица (10 цифр)
            Pattern(
                name="inn_individual",
                regex=r"\b\d{10}\b",
                score=0.8
            ),
            # ИНН юридического лица (12 цифр)
            Pattern(
                name="inn_legal",
                regex=r"\b\d{12}\b",
                score=0.8
            ),
        ]
    )

    # Российский паспорт
    russian_passport_recognizer = PatternRecognizer(
        supported_entity="RUS_PASSPORT",
        patterns=[
            # Внутренний паспорт HA (10 цифр: 4 серия + 6 номер)
            Pattern(
                name="internal_passport",
                regex=r"\b\d{4}[- ]?\d{6}\b",
                score=0.85
            ),
        ]
    )

    # Российские водительские права
    russian_driver_license_recognizer = PatternRecognizer(
        supported_entity="RUS_DRIVER_LICENSE",
        patterns=[
            # Стандартный формат с разделителями: 77 01 397000
            Pattern(
                name="driver_license_numbers_only",
                regex=r"\b\d{2}[- ]?\d{2}[- ]?\d{6}\b",
                score=0.8
            ),
            # Компактный формат: 7701397000
            Pattern(
                name="driver_license_compact",
                regex=r"\b\d{10}\b",
                score=0.7
            )
        ]
    )

    # Российский СНИЛС
    russian_snils_recognizer = PatternRecognizer(
        supported_entity="RUS_SNILS",
        patterns=[
            # Стандартный формат с разделителями: 465-853-475 45
            Pattern(
                name="snils_standard",
                regex=r"\b\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}\b",
                score=0.85
            ),
            # Компактный формат: 46585347545
            Pattern(
                name="snils_compact",
                regex=r"\b\d{11}\b",
                score=0.8
            ),
        ]
    )

    # Российский ОГРНИП
    rus_ogrnip_recognizer = PatternRecognizer(
        supported_entity="RUS_OGRNIP",
        patterns=[
            # Компактный формат: 316861700133226
            Pattern(
                name="ogrnip_compact",
                regex=r"\b\d{15}\b",
                score=0.8
            ),
        ]
    )

    # Российский ОМС полис
    rus_oms_policy_recognizer = PatternRecognizer(
        supported_entity="RUS_OMS_POLICY",
        patterns=[
            # Старый формат (16 цифр): 12345 67890000000
            Pattern(
                name="oms_old_format",
                regex=r"\b\d{5}[- ]?\d{11}\b",
                score=0.85
            ),
            # Новый формат (16 цифр): 123 4567 890000000
            Pattern(
                name="oms_new_format",
                regex=r"\b\d{3}[- ]?\d{4}[- ]?\d{9}\b",
                score=0.85
            ),
            # Единый номер полиса (16 цифр): 1234567890000000
            Pattern(
                name="oms_compact",
                regex=r"\b\d{16}\b",
                score=0.8
            ),
        ],
    )

    rus_person_recognizer = RusPersonRecognizer()
    rus_location_recognizer = RusLocationRecognizer()

    return [
        russian_phone_recognizer,
        russian_bank_card_recognizer,
        russian_inn_recognizer,
        russian_passport_recognizer,
        russian_driver_license_recognizer,
        russian_snils_recognizer,
        rus_ogrnip_recognizer,
        rus_oms_policy_recognizer,
        rus_person_recognizer,
        rus_location_recognizer,
    ]
