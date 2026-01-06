from typing import Any

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import SEARCH_CONTENT_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_CONTENT_PHRASE_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_CONTENT_VECTOR_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_TITLE_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import SEARCH_TITLE_VECTOR_WEIGHT
from onyx.document_index.opensearch.schema import CHUNK_INDEX_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_VECTOR_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import MAX_CHUNK_SIZE_FIELD_NAME
from onyx.document_index.opensearch.schema import PUBLIC_FIELD_NAME
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_VECTOR_FIELD_NAME

# Normalization pipelines combine document scores from multiple query clauses.
# The number and ordering of weights should match the query clauses. The values
# of the weights should sum to 1.

# TODO(andrei): Turn all magic dictionaries to pydantic models.

MIN_MAX_NORMALIZATION_PIPELINE_NAME = "normalization_pipeline_min_max"
MIN_MAX_NORMALIZATION_PIPELINE_CONFIG = {
    "description": "Normalization for keyword and vector scores using min-max",
    "phase_results_processors": [
        {
            # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
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
            # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
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

assert (
    sum(
        [
            SEARCH_TITLE_VECTOR_WEIGHT,
            SEARCH_CONTENT_VECTOR_WEIGHT,
            SEARCH_TITLE_KEYWORD_WEIGHT,
            SEARCH_CONTENT_KEYWORD_WEIGHT,
            SEARCH_CONTENT_PHRASE_WEIGHT,
        ]
    )
    == 1.0
)


# By default OpenSearch will only return a maximum of this many results in a
# given search. This value is configurable in the index settings.
DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW = 10_000


class DocumentQuery:
    """
    TODO(andrei): Implement multi-phase search strategies.
    TODO(andrei): Implement document boost.
    TODO(andrei): Implement document age.
    """

    @staticmethod
    def get_from_document_id_query(
        document_id: str,
        tenant_state: TenantState,
        max_chunk_size: int,
        min_chunk_index: int | None,
        max_chunk_index: int | None,
        get_full_document: bool = True,
    ) -> dict[str, Any]:
        """
        Returns a final search query which gets chunks from a given document ID.

        This query can be directly supplied to the OpenSearch client.

        TODO(andrei): Currently capped at 10k results. Implement scroll/point in
        time for results so that we can return arbitrarily-many IDs.

        Args:
            document_id: Onyx document ID. Notably not an OpenSearch document
                ID, which points to what Onyx would refer to as a chunk.
            tenant_state: Tenant state containing the tenant ID.
            max_chunk_size: Document chunks are categorized by the maximum
                number of tokens they can hold. This parameter specifies the
                maximum size category of document chunks to retrieve.
            min_chunk_index: The minimum chunk index to retrieve, inclusive. If
                None, no minimum chunk index will be applied.
            max_chunk_index: The maximum chunk index to retrieve, inclusive. If
                None, no maximum chunk index will be applied.
            get_full_document: Whether to get the full document body. If False,
                OpenSearch will only return the matching document chunk IDs plus
                metadata; the source data will be omitted from the response. Use
                this for performance optimization if OpenSearch IDs are
                sufficient. Defaults to True.

        Returns:
            A dictionary representing the final ID search query.
        """
        filter_clauses: list[dict[str, Any]] = [
            {"term": {DOCUMENT_ID_FIELD_NAME: {"value": document_id}}}
        ]

        if tenant_state.tenant_id is not None:
            # TODO(andrei): Fix tenant stuff.
            filter_clauses.append(
                {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_state.tenant_id}}}
            )

        if min_chunk_index is not None or max_chunk_index is not None:
            range_clause: dict[str, Any] = {"range": {CHUNK_INDEX_FIELD_NAME: {}}}
            if min_chunk_index is not None:
                range_clause["range"][CHUNK_INDEX_FIELD_NAME]["gte"] = min_chunk_index
            if max_chunk_index is not None:
                range_clause["range"][CHUNK_INDEX_FIELD_NAME]["lte"] = max_chunk_index
            filter_clauses.append(range_clause)

        filter_clauses.append(
            {"term": {MAX_CHUNK_SIZE_FIELD_NAME: {"value": max_chunk_size}}}
        )

        final_get_ids_query: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
            # We include this to make sure OpenSearch does not revert to
            # returning some number of results less than the index max allowed
            # return size.
            "size": DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW,
            "_source": get_full_document,
        }

        return final_get_ids_query

    @staticmethod
    def delete_from_document_id_query(
        document_id: str,
        tenant_state: TenantState,
    ) -> dict[str, Any]:
        """
        Returns a final search query which deletes chunks from a given document
        ID.

        This query can be directly supplied to the OpenSearch client.

        Intended to be supplied to the OpenSearch client's delete_by_query
        method.

        TODO(andrei): There is no limit to the number of document chunks that
        can be deleted by this query. This could get expensive. Consider
        implementing batching.

        Args:
            document_id: Onyx document ID. Notably not an OpenSearch document
                ID, which points to what Onyx would refer to as a chunk.
            tenant_state: Tenant state containing the tenant ID.

        Returns:
            A dictionary representing the final delete query.
        """
        filter_clauses: list[dict[str, Any]] = [
            {"term": {DOCUMENT_ID_FIELD_NAME: {"value": document_id}}}
        ]

        if tenant_state.tenant_id is not None:
            filter_clauses.append(
                {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_state.tenant_id}}}
            )

        final_delete_query: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
        }

        return final_delete_query

    @staticmethod
    def get_hybrid_search_query(
        query_text: str,
        query_vector: list[float],
        num_candidates: int,
        num_hits: int,
        tenant_state: TenantState,
    ) -> dict[str, Any]:
        """Returns a final hybrid search query.

        This query can be directly supplied to the OpenSearch client.

        Args:
            query_text: The text to query for.
            query_vector: The vector embedding of the text to query for.
            num_candidates: The number of candidates to consider for vector
                similarity search. Generally more candidates improves search
                quality at the cost of performance.
            num_hits: The final number of hits to return.
            tenant_state: Tenant state containing the tenant ID.

        Returns:
            A dictionary representing the final hybrid search query.
        """
        if num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            raise ValueError(
                f"Bug: num_hits ({num_hits}) is greater than the current maximum allowed "
                f"result window ({DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW})."
            )

        hybrid_search_subqueries = DocumentQuery._get_hybrid_search_subqueries(
            query_text, query_vector, num_candidates
        )
        hybrid_search_filters = DocumentQuery._get_hybrid_search_filters(tenant_state)

        hybrid_search_query: dict[str, Any] = {
            "bool": {
                "must": [
                    {
                        "hybrid": {
                            "queries": hybrid_search_subqueries,
                        }
                    }
                ],
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
    ) -> list[dict[str, Any]]:
        """Returns subqueries for hybrid search.

        Each of these subqueries are the "hybrid" component of this search. We
        search on various things and combine results.

        The return of this function is not sufficient to be directly supplied to
        the OpenSearch client. See get_hybrid_search_query.

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
        hybrid_search_queries: list[dict[str, Any]] = [
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
    def _get_hybrid_search_filters(tenant_state: TenantState) -> list[dict[str, Any]]:
        """Returns filters for hybrid search.

        For now only fetches public and not hidden documents.

        The return of this function is not sufficient to be directly supplied to
        the OpenSearch client. See get_hybrid_search_query.

        TODO(andrei): Add ACL filters and stuff.
        """
        hybrid_search_filters: list[dict[str, Any]] = [
            {"term": {PUBLIC_FIELD_NAME: {"value": True}}},
            {"term": {HIDDEN_FIELD_NAME: {"value": False}}},
        ]
        if tenant_state.tenant_id is not None:
            hybrid_search_filters.append(
                {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_state.tenant_id}}}
            )
        return hybrid_search_filters
