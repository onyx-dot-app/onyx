import random

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.llm.interfaces import LLM
from onyx.natural_language_processing.search_nlp_models import (
    ConnectorClassificationModel,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def strings_to_document_sources(source_strs: list[str]) -> list[DocumentSource]:
    sources = []
    for s in source_strs:
        try:
            sources.append(DocumentSource(s))
        except ValueError:
            logger.warning(f"Failed to translate {s} to a DocumentSource")
    return sources


def _sample_document_sources(
    valid_sources: list[DocumentSource],
    num_sample: int,
    allow_less: bool = True,
) -> list[DocumentSource]:
    if len(valid_sources) < num_sample:
        if not allow_less:
            raise RuntimeError("Not enough sample Document Sources")
        return random.sample(valid_sources, len(valid_sources))
    else:
        return random.sample(valid_sources, num_sample)


def _sample_documents_using_custom_connector_classifier(
    query: str,
    valid_sources: list[DocumentSource],
) -> list[DocumentSource] | None:
    query_joined = "".join(ch for ch in query.lower() if ch.isalnum())
    available_connectors = list(
        filter(
            lambda conn: conn.lower() in query_joined,
            [item.value for item in valid_sources],
        )
    )

    if not available_connectors:
        return None

    connectors = ConnectorClassificationModel().predict(query, available_connectors)

    return strings_to_document_sources(connectors) if connectors else None


def extract_source_filter(
    query: str, llm: LLM, db_session: Session
) -> list[DocumentSource] | None:
    # Can reference onyx/prompts/filter_extration.py for previous implementation prompts
    raise NotImplementedError("This function should not be getting called right now")
