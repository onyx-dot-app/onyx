import random
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import TypeAlias
from typing import TypeVar

from onyx.configs.app_configs import DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S
from onyx.configs.app_configs import OPENSEARCH_EXPLAIN_ENABLED
from onyx.configs.app_configs import OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED
from onyx.configs.app_configs import OPENSEARCH_PROFILING_DISABLED
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import Tag
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import ASSUMED_DOCUMENT_AGE_DAYS
from onyx.document_index.opensearch.constants import (
    DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES,
)
from onyx.document_index.opensearch.constants import (
    DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW,
)
from onyx.document_index.opensearch.constants import (
    HYBRID_SEARCH_NORMALIZATION_PIPELINE,
)
from onyx.document_index.opensearch.constants import (
    HYBRID_SEARCH_SUBQUERY_CONFIGURATION,
)
from onyx.document_index.opensearch.constants import HybridSearchNormalizationPipeline
from onyx.document_index.opensearch.constants import HybridSearchSubqueryConfiguration
from onyx.document_index.opensearch.schema import ACCESS_CONTROL_LIST_FIELD_NAME
from onyx.document_index.opensearch.schema import ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME
from onyx.document_index.opensearch.schema import CHUNK_INDEX_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_VECTOR_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_SETS_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import LAST_UPDATED_FIELD_NAME
from onyx.document_index.opensearch.schema import MAX_CHUNK_SIZE_FIELD_NAME
from onyx.document_index.opensearch.schema import METADATA_LIST_FIELD_NAME
from onyx.document_index.opensearch.schema import PERSONAS_FIELD_NAME
from onyx.document_index.opensearch.schema import PUBLIC_FIELD_NAME
from onyx.document_index.opensearch.schema import set_or_convert_timezone_to_utc
from onyx.document_index.opensearch.schema import SOURCE_TYPE_FIELD_NAME
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_VECTOR_FIELD_NAME
from onyx.document_index.opensearch.schema import USER_PROJECTS_FIELD_NAME

# See https://docs.opensearch.org/latest/query-dsl/term/terms/.
MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY = 65_536


T = TypeVar("T")
TermsQuery: TypeAlias = dict[str, dict[str, list[T]]]
TermQuery: TypeAlias = dict[str, dict[str, dict[str, T]]]


# TODO(andrei): Turn all magic dictionaries to pydantic models.


# Normalization pipelines combine document scores from multiple query clauses.
# The number and ordering of weights should match the query clauses. The values
# of the weights should sum to 1.
def _get_hybrid_search_normalization_weights() -> list[float]:
    if (
        HYBRID_SEARCH_SUBQUERY_CONFIGURATION
        is HybridSearchSubqueryConfiguration.TITLE_VECTOR_CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
    ):
        # Since the titles are included in the contents, the embedding matches
        # are heavily downweighted as they act as a boost rather than an
        # independent scoring component.
        search_title_vector_weight = 0.1
        search_content_vector_weight = 0.45
        # Single keyword weight for both title and content (merged from former
        # title keyword + content keyword).
        search_keyword_weight = 0.45

        # NOTE: It is critical that the order of these weights matches the order
        # of the sub-queries in the hybrid search.
        hybrid_search_normalization_weights = [
            search_title_vector_weight,
            search_content_vector_weight,
            search_keyword_weight,
        ]
    elif (
        HYBRID_SEARCH_SUBQUERY_CONFIGURATION
        is HybridSearchSubqueryConfiguration.CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
    ):
        search_content_vector_weight = 0.5
        # Single keyword weight for both title and content (merged from former
        # title keyword + content keyword).
        search_keyword_weight = 0.5

        # NOTE: It is critical that the order of these weights matches the order
        # of the sub-queries in the hybrid search.
        hybrid_search_normalization_weights = [
            search_content_vector_weight,
            search_keyword_weight,
        ]
    else:
        raise ValueError(
            f"Bug: Unhandled hybrid search subquery configuration: {HYBRID_SEARCH_SUBQUERY_CONFIGURATION}."
        )

    assert (
        sum(hybrid_search_normalization_weights) == 1.0
    ), "Bug: Hybrid search normalization weights do not sum to 1.0."

    return hybrid_search_normalization_weights


def get_min_max_normalization_pipeline_name_and_config() -> tuple[str, dict[str, Any]]:
    min_max_normalization_pipeline_name = "normalization_pipeline_min_max"
    min_max_normalization_pipeline_config: dict[str, Any] = {
        "description": "Normalization for keyword and vector scores using min-max",
        "phase_results_processors": [
            {
                # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {
                            "weights": _get_hybrid_search_normalization_weights()
                        },
                    },
                }
            }
        ],
    }
    return min_max_normalization_pipeline_name, min_max_normalization_pipeline_config


def get_zscore_normalization_pipeline_name_and_config() -> tuple[str, dict[str, Any]]:
    zscore_normalization_pipeline_name = "normalization_pipeline_zscore"
    zscore_normalization_pipeline_config: dict[str, Any] = {
        "description": "Normalization for keyword and vector scores using z-score",
        "phase_results_processors": [
            {
                # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
                "normalization-processor": {
                    "normalization": {"technique": "z_score"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {
                            "weights": _get_hybrid_search_normalization_weights()
                        },
                    },
                }
            }
        ],
    }
    return zscore_normalization_pipeline_name, zscore_normalization_pipeline_config


def get_normalization_pipeline_name_and_config() -> tuple[str, dict[str, Any]]:
    if (
        HYBRID_SEARCH_NORMALIZATION_PIPELINE
        is HybridSearchNormalizationPipeline.MIN_MAX
    ):
        return get_min_max_normalization_pipeline_name_and_config()
    elif (
        HYBRID_SEARCH_NORMALIZATION_PIPELINE is HybridSearchNormalizationPipeline.ZSCORE
    ):
        return get_zscore_normalization_pipeline_name_and_config()
    else:
        raise ValueError(
            f"Bug: Unhandled hybrid search normalization pipeline: {HYBRID_SEARCH_NORMALIZATION_PIPELINE}."
        )


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
        index_filters: IndexFilters,
        include_hidden: bool,
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
            index_filters: Filters for the document retrieval query.
            include_hidden: Whether to include hidden documents.
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
        filter_clauses = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            include_hidden=include_hidden,
            access_control_list=index_filters.access_control_list,
            source_types=index_filters.source_type or [],
            tags=index_filters.tags or [],
            document_sets=index_filters.document_set or [],
            project_id_filter=index_filters.project_id_filter,
            persona_id_filter=index_filters.persona_id_filter,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=min_chunk_index,
            max_chunk_index=max_chunk_index,
            max_chunk_size=max_chunk_size,
            document_id=document_id,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )
        final_get_ids_query: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
            # We include this to make sure OpenSearch does not revert to
            # returning some number of results less than the index max allowed
            # return size.
            "size": DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW,
            # By default exclude retrieving the vector fields in order to save
            # on retrieval cost as we don't need them upstream.
            "_source": {
                "excludes": [TITLE_VECTOR_FIELD_NAME, CONTENT_VECTOR_FIELD_NAME]
            },
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
        }
        if not get_full_document:
            # If we explicitly do not want the underlying document, we will only
            # retrieve IDs.
            final_get_ids_query["_source"] = False
        if not OPENSEARCH_PROFILING_DISABLED:
            final_get_ids_query["profile"] = True

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
        filter_clauses = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            # Delete hidden docs too.
            include_hidden=True,
            access_control_list=None,
            source_types=[],
            tags=[],
            document_sets=[],
            project_id_filter=None,
            persona_id_filter=None,
            time_cutoff=None,
            min_chunk_index=None,
            max_chunk_index=None,
            max_chunk_size=None,
            document_id=document_id,
        )
        final_delete_query: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
        }
        if not OPENSEARCH_PROFILING_DISABLED:
            final_delete_query["profile"] = True

        return final_delete_query

    @staticmethod
    def get_hybrid_search_query(
        query_text: str,
        query_vector: list[float],
        num_hits: int,
        tenant_state: TenantState,
        index_filters: IndexFilters,
        include_hidden: bool,
    ) -> dict[str, Any]:
        """Returns a final hybrid search query.

        NOTE: This query can be directly supplied to the OpenSearch client, but
        it MUST be supplied in addition to a search pipeline. The results from
        hybrid search are not meaningful without that step.

        Args:
            query_text: The text to query for.
            query_vector: The vector embedding of the text to query for.
            num_hits: The final number of hits to return.
            tenant_state: Tenant state containing the tenant ID.
            index_filters: Filters for the hybrid search query.
            include_hidden: Whether to include hidden documents.

        Returns:
            A dictionary representing the final hybrid search query.
        """
        # WARNING: Profiling does not work with hybrid search; do not add it at
        # this level. See https://github.com/opensearch-project/neural-search/issues/1255

        if num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            raise ValueError(
                f"Bug: num_hits ({num_hits}) is greater than the current maximum allowed "
                f"result window ({DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW})."
            )

        # TODO(andrei, yuhong): We can tune this more dynamically based on
        # num_hits.
        max_results_per_subquery = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES

        hybrid_search_subqueries = DocumentQuery._get_hybrid_search_subqueries(
            query_text, query_vector, vector_candidates=max_results_per_subquery
        )
        hybrid_search_filters = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            include_hidden=include_hidden,
            # TODO(andrei): We've done no filtering for PUBLIC_DOC_PAT up to
            # now. This should not cause any issues but it can introduce
            # redundant filters in queries that may affect performance.
            access_control_list=index_filters.access_control_list,
            source_types=index_filters.source_type or [],
            tags=index_filters.tags or [],
            document_sets=index_filters.document_set or [],
            project_id_filter=index_filters.project_id_filter,
            persona_id_filter=index_filters.persona_id_filter,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=None,
            max_chunk_index=None,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )

        # See https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
        hybrid_search_query: dict[str, Any] = {
            "hybrid": {
                "queries": hybrid_search_subqueries,
                # Max results per subquery per shard before aggregation. Ensures
                # keyword and vector subqueries contribute equally to the
                # candidate pool for hybrid fusion.
                # Sources:
                # https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/pagination/
                # https://opensearch.org/blog/navigating-pagination-in-hybrid-queries-with-the-pagination_depth-parameter/
                "pagination_depth": max_results_per_subquery,
                # Applied to all the sub-queries independently (this avoids
                # subqueries having a lot of results thrown out during
                # aggregation).
                # Sources:
                # https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
                # https://opensearch.org/blog/introducing-common-filter-support-for-hybrid-search-queries
                # Does AND for each filter in the list.
                "filter": {"bool": {"filter": hybrid_search_filters}},
            }
        }

        final_hybrid_search_body: dict[str, Any] = {
            "query": hybrid_search_query,
            "size": num_hits,
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
            # Exclude retrieving the vector fields in order to save on
            # retrieval cost as we don't need them upstream.
            "_source": {
                "excludes": [TITLE_VECTOR_FIELD_NAME, CONTENT_VECTOR_FIELD_NAME]
            },
        }

        if not OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED:
            final_hybrid_search_body["highlight"] = (
                DocumentQuery._get_match_highlights_configuration()
            )

        # Explain is for scoring breakdowns. Setting this significantly
        # increases query latency.
        if OPENSEARCH_EXPLAIN_ENABLED:
            final_hybrid_search_body["explain"] = True

        return final_hybrid_search_body

    @staticmethod
    def get_keyword_search_query(
        query_text: str,
        num_hits: int,
        tenant_state: TenantState,
        index_filters: IndexFilters,
        include_hidden: bool,
    ) -> dict[str, Any]:
        """Returns a final keyword search query.

        This query can be directly supplied to the OpenSearch client.

        Args:
            query_text: The text to query for.
            num_hits: The final number of hits to return.
            tenant_state: Tenant state containing the tenant ID.
            index_filters: Filters for the keyword search query.
            include_hidden: Whether to include hidden documents.

        Returns:
            A dictionary representing the final keyword search query.
        """
        if num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            raise ValueError(
                f"Bug: num_hits ({num_hits}) is greater than the current maximum allowed "
                f"result window ({DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW})."
            )

        keyword_search_filters = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            include_hidden=include_hidden,
            # TODO(andrei): We've done no filtering for PUBLIC_DOC_PAT up to
            # now. This should not cause any issues but it can introduce
            # redundant filters in queries that may affect performance.
            access_control_list=index_filters.access_control_list,
            source_types=index_filters.source_type or [],
            tags=index_filters.tags or [],
            document_sets=index_filters.document_set or [],
            project_id_filter=index_filters.project_id_filter,
            persona_id_filter=index_filters.persona_id_filter,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=None,
            max_chunk_index=None,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )

        keyword_search_query = (
            DocumentQuery._get_title_content_combined_keyword_search_query(
                query_text, search_filters=keyword_search_filters
            )
        )

        final_keyword_search_query: dict[str, Any] = {
            "query": keyword_search_query,
            "size": num_hits,
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
            # Exclude retrieving the vector fields in order to save on
            # retrieval cost as we don't need them upstream.
            "_source": {
                "excludes": [TITLE_VECTOR_FIELD_NAME, CONTENT_VECTOR_FIELD_NAME]
            },
        }

        if not OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED:
            final_keyword_search_query["highlight"] = (
                DocumentQuery._get_match_highlights_configuration()
            )

        if not OPENSEARCH_PROFILING_DISABLED:
            final_keyword_search_query["profile"] = True

        # Explain is for scoring breakdowns. Setting this significantly
        # increases query latency.
        if OPENSEARCH_EXPLAIN_ENABLED:
            final_keyword_search_query["explain"] = True

        return final_keyword_search_query

    @staticmethod
    def get_semantic_search_query(
        query_embedding: list[float],
        num_hits: int,
        tenant_state: TenantState,
        index_filters: IndexFilters,
        include_hidden: bool,
    ) -> dict[str, Any]:
        """Returns a final semantic search query.

        This query can be directly supplied to the OpenSearch client.

        Args:
            query_embedding: The vector embedding of the text to query for.
            num_hits: The final number of hits to return.
            tenant_state: Tenant state containing the tenant ID.
            index_filters: Filters for the semantic search query.
            include_hidden: Whether to include hidden documents.

        Returns:
            A dictionary representing the final semantic search query.
        """
        if num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            raise ValueError(
                f"Bug: num_hits ({num_hits}) is greater than the current maximum allowed "
                f"result window ({DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW})."
            )

        semantic_search_filters = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            include_hidden=include_hidden,
            # TODO(andrei): We've done no filtering for PUBLIC_DOC_PAT up to
            # now. This should not cause any issues but it can introduce
            # redundant filters in queries that may affect performance.
            access_control_list=index_filters.access_control_list,
            source_types=index_filters.source_type or [],
            tags=index_filters.tags or [],
            document_sets=index_filters.document_set or [],
            project_id_filter=index_filters.project_id_filter,
            persona_id_filter=index_filters.persona_id_filter,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=None,
            max_chunk_index=None,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )

        semantic_search_query = (
            DocumentQuery._get_content_vector_similarity_search_query(
                query_embedding,
                vector_candidates=num_hits,
                search_filters=semantic_search_filters,
            )
        )

        final_semantic_search_query: dict[str, Any] = {
            "query": semantic_search_query,
            "size": num_hits,
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
            # Exclude retrieving the vector fields in order to save on
            # retrieval cost as we don't need them upstream.
            "_source": {
                "excludes": [TITLE_VECTOR_FIELD_NAME, CONTENT_VECTOR_FIELD_NAME]
            },
        }

        if not OPENSEARCH_PROFILING_DISABLED:
            final_semantic_search_query["profile"] = True

        # Explain is for scoring breakdowns. Setting this significantly
        # increases query latency.
        if OPENSEARCH_EXPLAIN_ENABLED:
            final_semantic_search_query["explain"] = True

        return final_semantic_search_query

    @staticmethod
    def get_random_search_query(
        tenant_state: TenantState,
        index_filters: IndexFilters,
        num_to_retrieve: int,
    ) -> dict[str, Any]:
        """Returns a final search query that gets document chunks randomly.

        Args:
            tenant_state: Tenant state containing the tenant ID.
            index_filters: Filters for the random search query.
            num_to_retrieve: Number of document chunks to retrieve.

        Returns:
            A dictionary representing the final random search query.
        """
        search_filters = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            include_hidden=False,
            access_control_list=index_filters.access_control_list,
            source_types=index_filters.source_type or [],
            tags=index_filters.tags or [],
            document_sets=index_filters.document_set or [],
            project_id_filter=index_filters.project_id_filter,
            persona_id_filter=index_filters.persona_id_filter,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=None,
            max_chunk_index=None,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )
        final_random_search_query = {
            "query": {
                "function_score": {
                    "query": {"bool": {"filter": search_filters}},
                    # See
                    # https://docs.opensearch.org/latest/query-dsl/compound/function-score/#the-random-score-function
                    "random_score": {
                        # We'll use a different seed per invocation.
                        "seed": random.randint(0, 1_000_000),
                        # Some field which has a unique value per document
                        # chunk.
                        "field": "_seq_no",
                    },
                    # Replaces whatever score was computed in the query.
                    "boost_mode": "replace",
                }
            },
            "size": num_to_retrieve,
            "timeout": f"{DEFAULT_OPENSEARCH_QUERY_TIMEOUT_S}s",
            # Exclude retrieving the vector fields in order to save on
            # retrieval cost as we don't need them upstream.
            "_source": {
                "excludes": [TITLE_VECTOR_FIELD_NAME, CONTENT_VECTOR_FIELD_NAME]
            },
        }
        if not OPENSEARCH_PROFILING_DISABLED:
            final_random_search_query["profile"] = True

        return final_random_search_query

    @staticmethod
    def _get_hybrid_search_subqueries(
        query_text: str,
        query_vector: list[float],
        # The default number of neighbors to consider for knn vector similarity
        # search. This is higher than the number of results because the scoring
        # is hybrid. For a detailed breakdown, see where the default value is
        # set.
        vector_candidates: int = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES,
    ) -> list[dict[str, Any]]:
        """Returns subqueries for hybrid search.

        Each of these subqueries are the "hybrid" component of this search. We
        search on various things and combine results.

        The return of this function is not sufficient to be directly supplied to
        the OpenSearch client. See get_hybrid_search_query.

        Normalization is not performed here.
        The weights of each of these subqueries should be configured in a search
        pipeline.

        The exact subqueries executed depend on the
        HYBRID_SEARCH_SUBQUERY_CONFIGURATION setting.

        NOTE: For OpenSearch, 5 is the maximum number of query clauses allowed
        in a single hybrid query. Source:
        https://docs.opensearch.org/latest/query-dsl/compound/hybrid/

        NOTE: Each query is independent during the search phase; there is no
        backfilling of scores for missing query components. What this means is
        that if a document was a good vector match but did not show up for
        keyword, it gets a score of 0 for the keyword component of the hybrid
        scoring. This is not as bad as just disregarding a score though as there
        is normalization applied after. So really it is "increasing" the missing
        score compared to if it was included and the range was renormalized.
        This does however mean that between docs that have high scores for say
        the vector field, the keyword scores between them are completely ignored
        unless they also showed up in the keyword query as a reasonably high
        match. TLDR, this is a bit of unique funky behavior but it seems ok.

        NOTE: Options considered and rejected:
        - minimum_should_match: Since it's hybrid search and users often provide
          semantic queries, there is often a lot of terms, and very low number
          of meaningful keywords (and a low ratio of keywords).
        - fuzziness AUTO: Typo tolerance (0/1/2 edit distance by term length).
          It's mostly for typos as the analyzer ("english" by default) already
          does some stemming and tokenization. In testing datasets, this makes
          recall slightly worse. It also is less performant so not really any
          reason to do it.

        Args:
            query_text: The text of the query to search for.
            query_vector: The vector embedding of the query to search for.
            num_candidates: The number of candidates to consider for vector
                similarity search.
        """
        # Build sub-queries for hybrid search. Order must match normalization
        # pipeline weights.
        if (
            HYBRID_SEARCH_SUBQUERY_CONFIGURATION
            is HybridSearchSubqueryConfiguration.TITLE_VECTOR_CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
        ):
            return [
                DocumentQuery._get_title_vector_similarity_search_query(
                    query_vector, vector_candidates
                ),
                DocumentQuery._get_content_vector_similarity_search_query(
                    query_vector, vector_candidates
                ),
                DocumentQuery._get_title_content_combined_keyword_search_query(
                    query_text
                ),
            ]
        elif (
            HYBRID_SEARCH_SUBQUERY_CONFIGURATION
            is HybridSearchSubqueryConfiguration.CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
        ):
            return [
                DocumentQuery._get_content_vector_similarity_search_query(
                    query_vector, vector_candidates
                ),
                DocumentQuery._get_title_content_combined_keyword_search_query(
                    query_text
                ),
            ]
        else:
            raise ValueError(
                f"Bug: Unhandled hybrid search subquery configuration: {HYBRID_SEARCH_SUBQUERY_CONFIGURATION}"
            )

    @staticmethod
    def _get_title_vector_similarity_search_query(
        query_vector: list[float],
        vector_candidates: int = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES,
    ) -> dict[str, Any]:
        return {
            "knn": {
                TITLE_VECTOR_FIELD_NAME: {
                    "vector": query_vector,
                    "k": vector_candidates,
                }
            }
        }

    @staticmethod
    def _get_content_vector_similarity_search_query(
        query_vector: list[float],
        vector_candidates: int = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES,
        search_filters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        query = {
            "knn": {
                CONTENT_VECTOR_FIELD_NAME: {
                    "vector": query_vector,
                    "k": vector_candidates,
                }
            }
        }

        if search_filters is not None:
            query["knn"][CONTENT_VECTOR_FIELD_NAME]["filter"] = {
                "bool": {"filter": search_filters}
            }

        return query

    @staticmethod
    def _get_title_content_combined_keyword_search_query(
        query_text: str,
        search_filters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        query = {
            "bool": {
                "should": [
                    {
                        "match": {
                            TITLE_FIELD_NAME: {
                                "query": query_text,
                                "operator": "or",
                                # The title fields are strongly discounted as
                                # they are included in the content. This just
                                # acts as a minor boost.
                                "boost": 0.1,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            TITLE_FIELD_NAME: {
                                "query": query_text,
                                "slop": 1,
                                "boost": 0.2,
                            }
                        }
                    },
                    {
                        # Analyzes the query and returns results which match any
                        # of the query's terms. More matches result in higher
                        # scores.
                        "match": {
                            CONTENT_FIELD_NAME: {
                                "query": query_text,
                                "operator": "or",
                                "boost": 1.0,
                            }
                        }
                    },
                    {
                        # Matches an exact phrase in a specified order.
                        "match_phrase": {
                            CONTENT_FIELD_NAME: {
                                "query": query_text,
                                # The number of words permitted between words of
                                # a query phrase and still result in a match.
                                "slop": 1,
                                "boost": 1.5,
                            }
                        }
                    },
                ],
                # Ensures at least one match subquery from the query is present
                # in the document. This defaults to 1, unless a filter or must
                # clause is supplied, in which case it defaults to 0.
                "minimum_should_match": 1,
            }
        }

        if search_filters is not None:
            query["bool"]["filter"] = search_filters

        return query

    @staticmethod
    def _get_search_filters(
        tenant_state: TenantState,
        include_hidden: bool,
        access_control_list: list[str] | None,
        source_types: list[DocumentSource],
        tags: list[Tag],
        document_sets: list[str],
        project_id_filter: int | None,
        persona_id_filter: int | None,
        time_cutoff: datetime | None,
        min_chunk_index: int | None,
        max_chunk_index: int | None,
        max_chunk_size: int | None = None,
        document_id: str | None = None,
        # Assistant knowledge filters
        attached_document_ids: list[str] | None = None,
        hierarchy_node_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Returns filters to be passed into the "filter" key of a search query.

        The "filter" key applies a logical AND operator to its elements, so
        every subfilter must evaluate to true in order for the document to be
        retrieved. This function returns a list of such subfilters.
        See https://docs.opensearch.org/latest/query-dsl/compound/bool/.

        TODO(ENG-3874): The terms queries returned by this function can be made
        more performant for large cardinality sets by sorting the values by
        their UTF-8 byte order.

        TODO(ENG-3875): This function can take even better advantage of filter
        caching by grouping "static" filters together into one sub-clause.

        Args:
            tenant_state: Tenant state containing the tenant ID.
            include_hidden: Whether to include hidden documents.
            access_control_list: Access control list for the documents to
                retrieve. If None, there is no restriction on the documents that
                can be retrieved. If not None, only public documents can be
                retrieved, or non-public documents where at least one acl
                provided here is present in the document's acl list.
            source_types: If supplied, only documents of one of these source
                types will be retrieved.
            tags: If supplied, only documents with an entry in their metadata
                list corresponding to a tag will be retrieved.
            document_sets: If supplied, only documents with at least one
                document set ID from this list will be retrieved.
            project_id_filter: If not None, only documents with this project ID
                in user projects will be retrieved. Additive — only applied
                when a knowledge scope already exists.
            persona_id_filter: If not None, only documents whose personas array
                contains this persona ID will be retrieved. Primary — creates
                a knowledge scope on its own.
            time_cutoff: Time cutoff for the documents to retrieve. If not None,
                Documents which were last updated before this date will not be
                returned. For documents which do not have a value for their last
                updated time, we assume some default age of
                ASSUMED_DOCUMENT_AGE_DAYS for when the document was last
                updated.
            min_chunk_index: The minimum chunk index to retrieve, inclusive. If
                None, no minimum chunk index will be applied.
            max_chunk_index: The maximum chunk index to retrieve, inclusive. If
                None, no maximum chunk index will be applied.
            max_chunk_size: The type of chunk to retrieve, specified by the
                maximum number of tokens it can hold. If None, no filter will be
                applied for this. Defaults to None.
                NOTE: See DocumentChunk.max_chunk_size.
            document_id: The document ID to retrieve. If None, no filter will be
                applied for this. Defaults to None.
            attached_document_ids: Document IDs explicitly attached to the
                assistant. If provided along with hierarchy_node_ids, documents
                matching EITHER criteria will be retrieved (OR logic).
            hierarchy_node_ids: Hierarchy node IDs (folders/spaces) attached to
                the assistant. Matches chunks where ancestor_hierarchy_node_ids
                contains any of these values.

        Raises:
            ValueError: document_id and attached_document_ids were supplied
                together. This is not allowed because they operate on the same
                schema field, and it does not semantically make sense to use
                them together.
            ValueError: Too many of one of the collection arguments was
                supplied.

        Returns:
            A list of filters to be passed into the "filter" key of a search
                query.
        """

        def _get_acl_visibility_filter(
            access_control_list: list[str],
        ) -> dict[str, dict[str, list[TermQuery[bool] | TermsQuery[str]] | int]]:
            """Returns a filter for the access control list.

            Since this returns an isolated bool should clause, it can be cached
            in OpenSearch independently of other clauses in _get_search_filters.

            Args:
                access_control_list: The access control list to restrict
                    documents to.

            Raises:
                ValueError: The number of access control list entries is greater
                    than MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the access control list.
            """
            # Logical OR operator on its elements.
            acl_visibility_filter: dict[str, dict[str, Any]] = {
                "bool": {
                    "should": [{"term": {PUBLIC_FIELD_NAME: {"value": True}}}],
                    "minimum_should_match": 1,
                }
            }
            if access_control_list:
                if len(access_control_list) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                    raise ValueError(
                        f"Too many access control list entries: {len(access_control_list)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                    )
                # Use terms instead of a list of term within a should clause
                # because Lucene will optimize the filtering for large sets of
                # terms. Small sets of terms are not expected to perform any
                # differently than individual term clauses.
                acl_subclause: TermsQuery[str] = {
                    "terms": {ACCESS_CONTROL_LIST_FIELD_NAME: list(access_control_list)}
                }
                acl_visibility_filter["bool"]["should"].append(acl_subclause)
            return acl_visibility_filter

        def _get_source_type_filter(
            source_types: list[DocumentSource],
        ) -> TermsQuery[str]:
            """Returns a filter for the source types.

            Since this returns an isolated terms clause, it can be cached in
            OpenSearch independently of other clauses in _get_search_filters.

            Args:
                source_types: The source types to restrict documents to.

            Raises:
                ValueError: The number of source types is greater than
                    MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the source types.
            """
            if len(source_types) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                raise ValueError(
                    f"Too many source types: {len(source_types)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                )
            # Use terms instead of a list of term within a should clause because
            # Lucene will optimize the filtering for large sets of terms. Small
            # sets of terms are not expected to perform any differently than
            # individual term clauses.
            return {
                "terms": {
                    SOURCE_TYPE_FIELD_NAME: [
                        source_type.value for source_type in source_types
                    ]
                }
            }

        def _get_tag_filter(tags: list[Tag]) -> TermsQuery[str]:
            """Returns a filter for the tags.

            Since this returns an isolated terms clause, it can be cached in
            OpenSearch independently of other clauses in _get_search_filters.

            Args:
                tags: The tags to restrict documents to.

            Raises:
                ValueError: The number of tags is greater than
                    MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the tags.
            """
            if len(tags) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                raise ValueError(
                    f"Too many tags: {len(tags)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                )
            # Kind of an abstraction leak, see
            # convert_metadata_dict_to_list_of_strings for why metadata list
            # entries are expected to look this way.
            tag_str_list = [
                f"{tag.tag_key}{INDEX_SEPARATOR}{tag.tag_value}" for tag in tags
            ]
            # Use terms instead of a list of term within a should clause because
            # Lucene will optimize the filtering for large sets of terms. Small
            # sets of terms are not expected to perform any differently than
            # individual term clauses.
            return {"terms": {METADATA_LIST_FIELD_NAME: tag_str_list}}

        def _get_document_set_filter(document_sets: list[str]) -> TermsQuery[str]:
            """Returns a filter for the document sets.

            Since this returns an isolated terms clause, it can be cached in
            OpenSearch independently of other clauses in _get_search_filters.

            Args:
                document_sets: The document sets to restrict documents to.

            Raises:
                ValueError: The number of document sets is greater than
                    MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the document sets.
            """
            if len(document_sets) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                raise ValueError(
                    f"Too many document sets: {len(document_sets)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                )
            # Use terms instead of a list of term within a should clause because
            # Lucene will optimize the filtering for large sets of terms. Small
            # sets of terms are not expected to perform any differently than
            # individual term clauses.
            return {"terms": {DOCUMENT_SETS_FIELD_NAME: list(document_sets)}}

        def _get_user_project_filter(project_id: int) -> TermQuery[int]:
            return {"term": {USER_PROJECTS_FIELD_NAME: {"value": project_id}}}

        def _get_persona_filter(persona_id: int) -> TermQuery[int]:
            return {"term": {PERSONAS_FIELD_NAME: {"value": persona_id}}}

        def _get_time_cutoff_filter(time_cutoff: datetime) -> dict[str, Any]:
            # Convert to UTC if not already so the cutoff is comparable to the
            # document data.
            time_cutoff = set_or_convert_timezone_to_utc(time_cutoff)
            # Logical OR operator on its elements.
            time_cutoff_filter: dict[str, Any] = {
                "bool": {"should": [], "minimum_should_match": 1}
            }
            time_cutoff_filter["bool"]["should"].append(
                {
                    "range": {
                        LAST_UPDATED_FIELD_NAME: {"gte": int(time_cutoff.timestamp())}
                    }
                }
            )
            if time_cutoff < datetime.now(timezone.utc) - timedelta(
                days=ASSUMED_DOCUMENT_AGE_DAYS
            ):
                # Since the time cutoff is older than ASSUMED_DOCUMENT_AGE_DAYS
                # ago, we include documents which have no
                # LAST_UPDATED_FIELD_NAME value.
                time_cutoff_filter["bool"]["should"].append(
                    {
                        "bool": {
                            "must_not": {"exists": {"field": LAST_UPDATED_FIELD_NAME}}
                        }
                    }
                )
            return time_cutoff_filter

        def _get_chunk_index_filter(
            min_chunk_index: int | None, max_chunk_index: int | None
        ) -> dict[str, Any]:
            range_clause: dict[str, Any] = {"range": {CHUNK_INDEX_FIELD_NAME: {}}}
            if min_chunk_index is not None:
                range_clause["range"][CHUNK_INDEX_FIELD_NAME]["gte"] = min_chunk_index
            if max_chunk_index is not None:
                range_clause["range"][CHUNK_INDEX_FIELD_NAME]["lte"] = max_chunk_index
            return range_clause

        def _get_attached_document_id_filter(
            doc_ids: list[str],
        ) -> TermsQuery[str]:
            """
            Returns a filter for documents explicitly attached to an assistant.

            Since this returns an isolated terms clause, it can be cached in
            OpenSearch independently of other clauses in _get_search_filters.

            Args:
                doc_ids: The document IDs to restrict documents to.

            Raises:
                ValueError: The number of document IDs is greater than
                    MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the document IDs.
            """
            if len(doc_ids) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                raise ValueError(
                    f"Too many document IDs: {len(doc_ids)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                )
            # Use terms instead of a list of term within a should clause because
            # Lucene will optimize the filtering for large sets of terms. Small
            # sets of terms are not expected to perform any differently than
            # individual term clauses.
            return {"terms": {DOCUMENT_ID_FIELD_NAME: list(doc_ids)}}

        def _get_hierarchy_node_filter(
            node_ids: list[int],
        ) -> TermsQuery[int]:
            """
            Returns a filter for chunks whose ancestors include any of the given
            hierarchy nodes.

            Since this returns an isolated terms clause, it can be cached in
            OpenSearch independently of other clauses in _get_search_filters.

            Args:
                node_ids: The hierarchy node IDs to restrict documents to.

            Raises:
                ValueError: The number of hierarchy node IDs is greater than
                    MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY.

            Returns:
                A filter for the hierarchy node IDs.
            """
            if len(node_ids) > MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY:
                raise ValueError(
                    f"Too many hierarchy node IDs: {len(node_ids)}. Max allowed: {MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY}."
                )
            # Use terms instead of a list of term within a should clause because
            # Lucene will optimize the filtering for large sets of terms. Small
            # sets of terms are not expected to perform any differently than
            # individual term clauses.
            return {"terms": {ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME: list(node_ids)}}

        if document_id is not None and attached_document_ids is not None:
            raise ValueError(
                "document_id and attached_document_ids cannot be used together."
            )

        filter_clauses: list[dict[str, Any]] = []

        if not include_hidden:
            filter_clauses.append({"term": {HIDDEN_FIELD_NAME: {"value": False}}})

        if access_control_list is not None:
            # If an access control list is provided, the caller can only
            # retrieve public documents, and non-public documents where at least
            # one acl provided here is present in the document's acl list. If
            # there is explicitly no list provided, we make no restrictions on
            # the documents that can be retrieved.
            filter_clauses.append(_get_acl_visibility_filter(access_control_list))

        if source_types:
            # If at least one source type is provided, the caller will only
            # retrieve documents whose source type is present in this input
            # list.
            filter_clauses.append(_get_source_type_filter(source_types))

        if tags:
            # If at least one tag is provided, the caller will only retrieve
            # documents where at least one tag provided here is present in the
            # document's metadata list.
            filter_clauses.append(_get_tag_filter(tags))

        # Knowledge scope: explicit knowledge attachments restrict what an
        # assistant can see. When none are set the assistant searches
        # everything.
        #
        # persona_id_filter is a primary trigger — a persona with user files IS
        # explicit knowledge, so it can start a knowledge scope on its own.
        #
        # project_id_filter is additive — it widens the scope to also cover
        # overflowing project files but never restricts on its own (a chat
        # inside a project should still search team knowledge).
        has_knowledge_scope = (
            attached_document_ids
            or hierarchy_node_ids
            or document_sets
            or persona_id_filter is not None
        )

        if has_knowledge_scope:
            # Since this returns an isolated bool should clause, it can be
            # cached in OpenSearch independently of other clauses in
            # _get_search_filters.
            knowledge_filter: dict[str, Any] = {
                "bool": {"should": [], "minimum_should_match": 1}
            }
            if attached_document_ids:
                knowledge_filter["bool"]["should"].append(
                    _get_attached_document_id_filter(attached_document_ids)
                )
            if hierarchy_node_ids:
                knowledge_filter["bool"]["should"].append(
                    _get_hierarchy_node_filter(hierarchy_node_ids)
                )
            if document_sets:
                knowledge_filter["bool"]["should"].append(
                    _get_document_set_filter(document_sets)
                )
            if persona_id_filter is not None:
                knowledge_filter["bool"]["should"].append(
                    _get_persona_filter(persona_id_filter)
                )
            if project_id_filter is not None:
                knowledge_filter["bool"]["should"].append(
                    _get_user_project_filter(project_id_filter)
                )
            filter_clauses.append(knowledge_filter)

        if time_cutoff is not None:
            # If a time cutoff is provided, the caller will only retrieve
            # documents where the document was last updated at or after the time
            # cutoff. For documents which do not have a value for
            # LAST_UPDATED_FIELD_NAME, we assume some default age for the
            # purposes of time cutoff.
            filter_clauses.append(_get_time_cutoff_filter(time_cutoff))

        if min_chunk_index is not None or max_chunk_index is not None:
            filter_clauses.append(
                _get_chunk_index_filter(min_chunk_index, max_chunk_index)
            )

        if document_id is not None:
            filter_clauses.append(
                {"term": {DOCUMENT_ID_FIELD_NAME: {"value": document_id}}}
            )

        if max_chunk_size is not None:
            filter_clauses.append(
                {"term": {MAX_CHUNK_SIZE_FIELD_NAME: {"value": max_chunk_size}}}
            )

        if tenant_state.multitenant:
            filter_clauses.append(
                {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_state.tenant_id}}}
            )

        return filter_clauses

    @staticmethod
    def _get_match_highlights_configuration() -> dict[str, Any]:
        """
        Gets configuration for returning match highlights for a hit.
        """
        match_highlights_configuration: dict[str, Any] = {
            "fields": {
                CONTENT_FIELD_NAME: {
                    # See https://docs.opensearch.org/latest/search-plugins/searching-data/highlight/#highlighter-types
                    "type": "unified",
                    # The length in chars of a match snippet. Somewhat
                    # arbitrarily-chosen. The Vespa codepath limited total
                    # highlights length to 400 chars. fragment_size *
                    # number_of_fragments = 400 should be good enough.
                    "fragment_size": 100,
                    # The number of snippets to return per field per document
                    # hit.
                    "number_of_fragments": 4,
                    # These tags wrap matched keywords and they match what Vespa
                    # used to return. Use them to minimize changes to our code.
                    "pre_tags": ["<hi>"],
                    "post_tags": ["</hi>"],
                }
            }
        }

        return match_highlights_configuration
