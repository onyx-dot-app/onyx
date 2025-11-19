from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

from onyx.server.features.guardrails.services.custom_recognizers import create_custom_recognizers
from onyx.utils.logger import setup_logger

logger = setup_logger()

configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}

provider = NlpEngineProvider(nlp_configuration=configuration)
nlp_engine = provider.create_engine()

_analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
_anonymizer = AnonymizerEngine()

if hasattr(_analyzer, 'nlp_engine') and _analyzer.nlp_engine:
    models_info = []
    for lang_code, nlp_model in _analyzer.nlp_engine.nlp.items():
        model_name = nlp_model.meta.get("name", "unknown")
        model_version = nlp_model.meta.get("version", "unknown")
        models_info.append(f"{lang_code}: {model_name} (v{model_version})")

    logger.info(
        "\nКонфигурация Analyzer Presidio:\n"
        "- NLP движок: %s\n"
        "- Загруженные модели: %s\n"
        "- Количество моделей: %d",
        _analyzer.nlp_engine.engine_name,
        ", ".join(models_info),
        len(models_info)
    )
else:
    logger.warning("NLP движок Presidio не инициализирован")


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
