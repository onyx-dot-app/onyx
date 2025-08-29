from pydantic import BaseModel
from onyx.db.models import KnowledgeMap as KnowledgeMapDBModel
from onyx.db.models import KnowledgeMapAnswer as KnowledgeMapAnswerDBModel


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


class KnowledgeMapAnswer(BaseModel):
    id: int
    document_id: str
    knowledge_map_id: int
    topic: str
    answer: str

    @classmethod
    def from_model(cls, answer: KnowledgeMapAnswerDBModel):
        return cls(
            id=answer.id,
            document_id=answer.document_id,
            knowledge_map_id=answer.knowledge_map_id,
            topic=answer.topic,
            answer=answer.answer
        )


class KnowledgeMap(BaseModel):
    id: int
    name: str
    description: str
    document_set_id: int
    flowise_pipeline_id: str
    answers: list["KnowledgeMapAnswer"]

    @classmethod
    def from_model(cls, knowledge_map_model: KnowledgeMapDBModel, answers_db: list[KnowledgeMapAnswerDBModel]):
        return cls(
            id=knowledge_map_model.id,
            name=knowledge_map_model.name,
            description=knowledge_map_model.description,
            document_set_id=knowledge_map_model.document_set_id,
            flowise_pipeline_id=knowledge_map_model.flowise_pipeline_id,
            answers=[KnowledgeMapAnswer.from_model(answer) for answer in answers_db]
        )