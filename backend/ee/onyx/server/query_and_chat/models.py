from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import BasicChunkRequest
from onyx.context.search.models import InferenceChunk
from onyx.server.manage.models import StandardAnswer


class StandardAnswerRequest(BaseModel):
    message: str
    slack_bot_categories: list[str]


class StandardAnswerResponse(BaseModel):
    standard_answers: list[StandardAnswer] = Field(default_factory=list)


class DocumentSearchRequest(BasicChunkRequest):
    user_selected_filters: BaseFilters | None = None


class DocumentSearchResponse(BaseModel):
    top_documents: list[InferenceChunk]
