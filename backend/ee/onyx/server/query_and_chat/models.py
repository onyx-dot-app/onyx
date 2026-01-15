from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import SearchDoc
from onyx.server.manage.models import StandardAnswer


class StandardAnswerRequest(BaseModel):
    message: str
    slack_bot_categories: list[str]


class StandardAnswerResponse(BaseModel):
    standard_answers: list[StandardAnswer] = Field(default_factory=list)


class SearchFlowClassificationRequest(BaseModel):
    user_query: str


class SearchFlowClassificationResponse(BaseModel):
    is_search_flow: bool


class SendSearchQueryRequest(BaseModel):
    search_query: str
    filters: BaseFilters | None = None
    num_docs_fed_to_llm_selection: int | None = None
    run_query_expansion: bool = False
    stream: bool = False


class SearchFullResponse(BaseModel):
    all_executed_queries: list[str]
    search_docs: list[SearchDoc]
    # Reasoning tokens output by the LLM for the document selection
    doc_selection_reasoning: str | None = None
    # This a list of document ids that are in the search_docs list
    llm_selected_doc_ids: list[str] | None = None
    # Error message if the search failed partway through
    error: str | None = None
