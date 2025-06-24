from pydantic import BaseModel
from onyx.db.models import KnowledgeMap as KnowledgeMapDBModel


class CreateKnowledgeMapRequest(BaseModel):
    name: str
    description: str
    document_set_id: int
    flowise_pipeline_id: str


class EditKnowledgeMapRequest(BaseModel):
    id: int
    name: str
    description: str
    document_set_id: int
    flowise_pipeline_id: str


class KnowledgeMap(BaseModel):
    id: int
    name: str
    description: str
    document_set_id: int
    flowise_pipeline_id: str

    @classmethod
    def from_model(cls, knowledge_map_model: KnowledgeMapDBModel):
        return cls(
            id=knowledge_map_model.id,
            name=knowledge_map_model.name,
            description=knowledge_map_model.description,
            document_set_id=knowledge_map_model.document_set_id,
            flowise_pipeline_id=knowledge_map_model.flowise_pipeline_id
        )