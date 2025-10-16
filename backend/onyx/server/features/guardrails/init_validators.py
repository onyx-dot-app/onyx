from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

from onyx.server.features.guardrails.services.custom_recognizers import create_custom_recognizers
from onyx.utils.logger import setup_logger

logger = setup_logger()

_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def initialize_presidio_analyzer():
    """Инициализирует Presidio Analyzer Engine
    с кастомными распознавателями PII entities
    """
    custom_recognizers = create_custom_recognizers()

    for recognizer in custom_recognizers:
        _analyzer.registry.add_recognizer(recognizer)

    logger.info(
        "Загружены кастомные распознаватели (PII entities) для Presidio"
    )
