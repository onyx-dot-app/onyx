from typing import Dict

from onyx.kg.context_preparations_extraction.fireflies import (
    prepare_llm_content_fireflies,
)
from onyx.kg.context_preparations_extraction.fireflies import (
    prepare_llm_document_content_fireflies,
)
from onyx.kg.context_preparations_extraction.models import ContextPreparation
from onyx.kg.context_preparations_extraction.models import (
    KGDocumentClassificationPrompt,
)
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent


def prepare_llm_content(chunk: KGChunkFormat) -> ContextPreparation:
    """
    Prepare the content for the LLM.
    """
    if chunk.source_type == "fireflies":
        return prepare_llm_content_fireflies(chunk)

    else:
        return ContextPreparation(
            llm_context=chunk.content,
            core_entity="",
            implied_entities=[],
            implied_relationships=[],
            implied_terms=[],
        )


def prepare_llm_document_content(
    document_classification_content: KGClassificationContent,
    category_list: str,
    category_definitions: dict[str, Dict[str, str | bool]],
) -> KGDocumentClassificationPrompt:
    """
    Prepare the content for the extraction classification.
    """

    category_definition_string = ""
    for category, category_data in category_definitions.items():
        category_definition_string += f"{category}: {category_data['description']}\n"

    if document_classification_content.source_type == "fireflies":
        return prepare_llm_document_content_fireflies(
            document_classification_content, category_list, category_definition_string
        )

    else:
        return KGDocumentClassificationPrompt(
            llm_prompt=None,
        )
