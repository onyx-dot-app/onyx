from pydantic import BaseModel


class AgentDocumentCitations(BaseModel):
    document_id: str
    document_title: str
    link: str
