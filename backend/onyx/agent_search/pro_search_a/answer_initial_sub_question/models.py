from pydantic import BaseModel


### Models ###


class AnswerRetrievalStats(BaseModel):
    answer_retrieval_stats: dict[str, float | int]
