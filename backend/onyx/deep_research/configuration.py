from pydantic import BaseModel

from onyx.llm.models import ReasoningEffort


class ResearchConfiguration(BaseModel):
    """Settings needed to rebuild a research agent for another run."""

    language_section: str
    reasoning_effort: ReasoningEffort
