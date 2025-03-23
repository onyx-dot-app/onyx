from pydantic import BaseModel


class ContextPreparation(BaseModel):
    """
    Context preparation format for the LLM KG extraction.
    """

    llm_context: str
    implied_entities: list[str]
    implied_relationships: list[str]
    implied_terms: list[str]
