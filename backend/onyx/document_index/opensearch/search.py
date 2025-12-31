from typing import Any

from onyx.document_index.opensearch.constants import SEARCH_CONTENT_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_CONTENT_PHRASE_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_CONTENT_VECTOR_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_TITLE_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_TITLE_VECTOR_WEIGHT
from onyx.document_index.opensearch.schema import CONTENT_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_VECTOR_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import PUBLIC_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_VECTOR_FIELD_NAME

# Normalization pipelines combine document scores from multiple query clauses.
# The number and ordering of weights should match the query clauses. The values
# of the weights should sum to 1.

MIN_MAX_NORMALIZATION_PIPELINE_NAME = "normalization_pipeline_min_max"
MIN_MAX_NORMALIZATION_PIPELINE_CONFIG = {
    "description": "Normalization for keyword and vector scores using min-max",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {
                        "weights": [
                            SEARCH_TITLE_VECTOR_WEIGHT,
                            SEARCH_CONTENT_VECTOR_WEIGHT,
                            SEARCH_TITLE_KEYWORD_WEIGHT,
                            SEARCH_CONTENT_KEYWORD_WEIGHT,
                            SEARCH_CONTENT_PHRASE_WEIGHT,
                        ]
                    },
                },
            }
        }
    ],
}

ZSCORE_NORMALIZATION_PIPELINE_NAME = "normalization_pipeline_zscore"
ZSCORE_NORMALIZATION_PIPELINE_CONFIG = {
    "description": "Normalization for keyword and vector scores using z-score",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "z_score"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {
                        "weights": [
                            SEARCH_TITLE_VECTOR_WEIGHT,
                            SEARCH_CONTENT_VECTOR_WEIGHT,
                            SEARCH_TITLE_KEYWORD_WEIGHT,
                            SEARCH_CONTENT_KEYWORD_WEIGHT,
                            SEARCH_CONTENT_PHRASE_WEIGHT,
                        ]
                    },
                },
            }
        }
    ],
}


class DocumentQuery:
    @staticmethod
    def get_hybrid_search_query(
        query_text: str, query_vector: list[float], num_candidates: int, num_hits: int
    ) -> dict[str, Any]:
        hybrid_search_subqueries = DocumentQuery._get_hybrid_search_subqueries(
            query_text, query_vector, num_candidates
        )
        hybrid_search_filters = DocumentQuery._get_hybrid_search_filters()
        hybrid_search_query: dict[str, Any] = {
            "hybrid": {
                "queries": hybrid_search_subqueries,
                "filter": hybrid_search_filters,
            }
        }

        final_hybrid_search_body: dict[str, Any] = {
            "query": hybrid_search_query,
            "size": num_hits,
        }
        return final_hybrid_search_body

    @staticmethod
    def _get_hybrid_search_subqueries(
        query_text: str, query_vector: list[float], num_candidates: int
    ) -> list[Any]:
        """Returns subqueries for hybrid search.

        Matches:
          - Title vector
          - Content vector
          - Title keyword
          - Content keyword
          - Content phrase

        Normalization is not performed here.
        The weights of each of these subqueries should be configured in a search
        pipeline.

        NOTE: For OpenSearch, 5 is the maximum number of query clauses allowed
        in a single hybrid query.

        Args:
            query_text: The text of the query to search for.
            query_vector: The vector embedding of the query to search for.
            num_candidates: The number of candidates to consider for vector
                similarity search.
        """
        hybrid_search_queries = [
            {
                "knn": {
                    TITLE_VECTOR_FIELD_NAME: {
                        "vector": query_vector,
                        "k": num_candidates,
                    }
                }
            },
            {
                "knn": {
                    CONTENT_VECTOR_FIELD_NAME: {
                        "vector": query_vector,
                        "k": num_candidates,
                    }
                }
            },
            {
                "multi_match": {
                    "query": query_text,
                    "fields": [f"{TITLE_FIELD_NAME}^2", f"{TITLE_FIELD_NAME}.keyword"],
                    "type": "best_fields",
                }
            },
            {"match": {CONTENT_FIELD_NAME: {"query": query_text}}},
            {"match_phrase": {CONTENT_FIELD_NAME: {"query": query_text, "boost": 1.5}}},
        ]
        return hybrid_search_queries

    @staticmethod
    def _get_hybrid_search_filters() -> list[Any]:
        """Returns filters for hybrid search.

        For now only fetches public and not hidden documents.

        TODO(andrei): Add ACL filters and stuff.
        """
        hybrid_search_filters = [
            {"term": {PUBLIC_FIELD_NAME: {"value": True}}},
            {"term": {HIDDEN_FIELD_NAME: {"value": False}}},
        ]
        return hybrid_search_filters
