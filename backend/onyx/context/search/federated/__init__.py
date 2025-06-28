from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.document import DocumentSource

FEDERATED_SEARCH_FUNCTIONS: dict[
    DocumentSource, Callable[[SearchQuery, Session], list[InferenceChunk]]
] = {
    DocumentSource.SLACK: slack_retrieval,
}
