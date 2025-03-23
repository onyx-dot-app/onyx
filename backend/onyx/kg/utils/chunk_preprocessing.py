from onyx.kg.context_preparations_extraction.fireflies import (
    prepare_llm_content_fireflies,
)
from onyx.kg.context_preparations_extraction.models import ContextPreparation
from onyx.kg.models import KGChunkFormat


def prepare_llm_content(chunk: KGChunkFormat) -> ContextPreparation:
    """
    Prepare the content for the LLM.
    """
    if chunk.source_type == "fireflies":
        return prepare_llm_content_fireflies(chunk)

    else:
        return ContextPreparation(
            llm_context=chunk.content,
            implied_entities=[],
            implied_relationships=[],
            implied_terms=[],
        )
