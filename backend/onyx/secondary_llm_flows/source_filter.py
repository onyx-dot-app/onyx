from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.llm.interfaces import LLM
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


def extract_source_filter(
    query: str, llm: LLM, db_session: Session
) -> list[DocumentSource] | None:
    # Can reference onyx/prompts/filter_extration.py for previous implementation prompts
    raise NotImplementedError("This function should not be getting called right now")
