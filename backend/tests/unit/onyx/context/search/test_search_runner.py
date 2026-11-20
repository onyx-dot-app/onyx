from unittest.mock import MagicMock

from onyx.context.search.models import ChunkIndexRequest, IndexFilters
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.document_index.interfaces import DocumentIndex
from onyx.tools.tool_implementations.search.constants import KEYWORD_ONLY_HYBRID_ALPHA


def test_keyword_only_retrieval_embeds_nothing() -> None:
    index = MagicMock(spec=DocumentIndex)
    index.keyword_retrieval.return_value = []
    embedding_model = MagicMock()

    search_chunks(
        query_request=ChunkIndexRequest(
            query="rollback ownership",
            hybrid_alpha=KEYWORD_ONLY_HYBRID_ALPHA,
            filters=IndexFilters(access_control_list=None),
        ),
        user_id=None,
        document_index=index,
        embedding_model=embedding_model,
        prefetched_federated_retrieval_infos=[],
    )

    index.keyword_retrieval.assert_called_once()
    index.hybrid_retrieval.assert_not_called()
    embedding_model.encode.assert_not_called()
