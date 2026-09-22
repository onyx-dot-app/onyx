from pydantic import BaseModel

from onyx.chat.citation_processor import CitationMapping


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    citation_mapping: CitationMapping
