from pydantic import BaseModel


class ContextPreparation(BaseModel):
    """
    Context preparation format for the LLM KG extraction.
    """

    llm_context: str
    core_entity: str
    implied_entities: list[str]
    implied_relationships: list[str]
    implied_terms: list[str]


class KGDocumentClassificationPrompt(BaseModel):
    """
    Document classification prompt format for the LLM KG extraction.
    """

    llm_prompt: str | None
