import random
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import UUID

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import Tag
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import DEFAULT_K_NUM_CANDIDATES
from onyx.document_index.opensearch.constants import HYBRID_SEARCH_NORMALIZATION_WEIGHTS
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
from onyx.document_index.opensearch.schema import PUBLIC_FIELD_NAME
from onyx.document_index.opensearch.schema import set_or_convert_timezone_to_utc
from onyx.document_index.opensearch.schema import SOURCE_TYPE_FIELD_NAME
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_FIELD_NAME
from onyx.document_index.opensearch.schema import TITLE_VECTOR_FIELD_NAME
from onyx.document_index.opensearch.schema import USER_PROJECTS_FIELD_NAME

# Normalization pipelines combine document scores from multiple query clauses.
# The number and ordering of weights should match the query clauses. The values
# of the weights should sum to 1.

# TODO(andrei): Turn all magic dictionaries to pydantic models.

MIN_MAX_NORMALIZATION_PIPELINE_NAME = "normalization_pipeline_min_max"
MIN_MAX_NORMALIZATION_PIPELINE_CONFIG: dict[str, Any] = {
    "description": "Normalization for keyword and vector scores using min-max",
    "phase_results_processors": [
        {
            # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": HYBRID_SEARCH_NORMALIZATION_WEIGHTS},
                },
            }
        }
    ],
}

ZSCORE_NORMALIZATION_PIPELINE_NAME = "normalization_pipeline_zscore"
ZSCORE_NORMALIZATION_PIPELINE_CONFIG: dict[str, Any] = {
    "description": "Normalization for keyword and vector scores using z-score",
    "phase_results_processors": [
        {
            # https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
            "normalization-processor": {
                "normalization": {"technique": "z_score"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": HYBRID_SEARCH_NORMALIZATION_WEIGHTS},
                },
            }
        }
    ],
}


# By default OpenSearch will only return a maximum of this many results in a
# given search. This value is configurable in the index settings.
DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW = 10_000

# For documents which do not have a value for LAST_UPDATED_FIELD_NAME, we assume
# that the document was last updated this many days ago for the purpose of time
# cutoff filtering during retrieval.
ASSUMED_DOCUMENT_AGE_DAYS = 90


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
            user_file_ids=index_filters.user_file_ids or [],
            project_id=index_filters.project_id,
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
        filter_clauses = DocumentQuery._get_search_filters(
            tenant_state=tenant_state,
            # Delete hidden docs too.
            include_hidden=True,
            access_control_list=None,
            source_types=[],
            tags=[],
            document_sets=[],
            user_file_ids=[],
            project_id=None,
            time_cutoff=None,
            min_chunk_index=None,
            max_chunk_index=None,
            max_chunk_size=None,
            document_id=document_id,
        )
        final_delete_query: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
        }

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
        if num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            raise ValueError(
                f"Bug: num_hits ({num_hits}) is greater than the current maximum allowed "
                f"result window ({DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW})."
            )

        hybrid_search_subqueries = DocumentQuery._get_hybrid_search_subqueries(
            query_text, query_vector, num_candidates=DEFAULT_K_NUM_CANDIDATES
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
            user_file_ids=index_filters.user_file_ids or [],
            project_id=index_filters.project_id,
            time_cutoff=index_filters.time_cutoff,
            min_chunk_index=None,
            max_chunk_index=None,
            attached_document_ids=index_filters.attached_document_ids,
            hierarchy_node_ids=index_filters.hierarchy_node_ids,
        )
        match_highlights_configuration = (
            DocumentQuery._get_match_highlights_configuration()
        )

        # See https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
        hybrid_search_query: dict[str, Any] = {
            "hybrid": {
                "queries": hybrid_search_subqueries,
                # Applied to all the sub-queries. Source:
                # https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
                # Does AND for each filter in the list.
                "filter": {"bool": {"filter": hybrid_search_filters}},
            }
        }

        # NOTE: By default, hybrid search retrieves "size"-many results from
        # each OpenSearch shard before aggregation. Source:
        # https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/pagination/

        final_hybrid_search_body: dict[str, Any] = {
            "query": hybrid_search_query,
            "size": num_hits,
            "highlight": match_highlights_configuration,
        }

        return final_hybrid_search_body

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
            user_file_ids=index_filters.user_file_ids or [],
            project_id=index_filters.project_id,
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
        }

        return final_random_search_query

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
          - Title keyword
          - Content vector
          - Content keyword + phrase

        Normalization is not performed here.
        The weights of each of these subqueries should be configured in a search
        pipeline.

        NOTE: For OpenSearch, 5 is the maximum number of query clauses allowed
        in a single hybrid query. Source:
        https://docs.opensearch.org/latest/query-dsl/compound/hybrid/

        NOTE: Each query is independent during the search phase, there is no backfilling of scores for missing query components.
        What this means is that if a document was a good vector match but did not show up for keyword, it gets a score of 0 for
        the keyword component of the hybrid scoring. This is not as bad as just disregarding a score though as there is
        normalization applied after. So really it is "increasing" the missing score compared to if it was included and the range
        was renormalized. This does however mean that between docs that have high scores for say the vector field, the keyword
        scores between them are completely ignored unless they also showed up in the keyword query as a reasonably high match.
        TLDR, this is a bit of unique funky behavior but it seems ok.

        NOTE: Options considered and rejected:
        - minimum_should_match: Since it's hybrid search and users often provide semantic queries, there is often a lot of terms,
          and very low number of meaningful keywords (and a low ratio of keywords).
        - fuzziness AUTO: typo tolerance (0/1/2 edit distance by term length). This is reasonable but in reality seeing the
          user usage patterns, this is not very common and people tend to not be confused when a miss happens for this reason.
          In testing datasets, this makes recall slightly worse.

        Args:
            query_text: The text of the query to search for.
            query_vector: The vector embedding of the query to search for.
            num_candidates: The number of candidates to consider for vector
                similarity search.
        """
        # Build sub-queries for hybrid search. Order must match normalization
        # pipeline weights: title vector, title keyword, content vector,
        # content keyword.
        hybrid_search_queries: list[dict[str, Any]] = [
            # 1. Title vector search
            {
                "knn": {
                    TITLE_VECTOR_FIELD_NAME: {
                        "vector": query_vector,
                        "k": num_candidates,
                    }
                }
            },
            # 2. Title keyword + phrase search.
            {
                "bool": {
                    "should": [
                        {
                            "match": {
                                TITLE_FIELD_NAME: {
                                    "query": query_text,
                                    # operator "or" = match doc if any query term matches (default, explicit for clarity).
                                    "operator": "or",
                                }
                            }
                        },
                        {
                            "match_phrase": {
                                TITLE_FIELD_NAME: {
                                    "query": query_text,
                                    # Slop = 1 allows one extra word or transposition in phrase match.
                                    "slop": 1,
                                    # Boost phrase over bag-of-words; exact phrase is a stronger signal.
                                    "boost": 1.5,
                                }
                            }
                        },
                    ]
                }
            },
            # 3. Content vector search
            {
                "knn": {
                    CONTENT_VECTOR_FIELD_NAME: {
                        "vector": query_vector,
                        "k": num_candidates,
                    }
                }
            },
            # 4. Content keyword + phrase search.
            {
                "bool": {
                    "should": [
                        {
                            "match": {
                                CONTENT_FIELD_NAME: {
                                    "query": query_text,
                                    # operator "or" = match doc if any query term matches (default, explicit for clarity).
                                    "operator": "or",
                                }
                            }
                        },
                        {
                            "match_phrase": {
                                CONTENT_FIELD_NAME: {
                                    "query": query_text,
                                    # Slop = 1 allows one extra word or transposition in phrase match.
                                    "slop": 1,
                                    # Boost phrase over bag-of-words; exact phrase is a stronger signal.
                                    "boost": 1.5,
                                }
                            }
                        },
                    ]
                }
            },
        ]

        return hybrid_search_queries

    @staticmethod
    def _get_search_filters(
        tenant_state: TenantState,
        include_hidden: bool,
        access_control_list: list[str] | None,
        source_types: list[DocumentSource],
        tags: list[Tag],
        document_sets: list[str],
        user_file_ids: list[UUID],
        project_id: int | None,
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
        See https://docs.opensearch.org/latest/query-dsl/compound/bool/

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
            user_file_ids: If supplied, only document IDs in this list will be
                retrieved.
            project_id: If not None, only documents with this project ID in user
                projects will be retrieved.
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
                WARNING: This filters on the same property as user_file_ids.
                Although it would never make sense to supply both, note that if
                user_file_ids is supplied and does not contain document_id, no
                matches will be retrieved.
            attached_document_ids: Document IDs explicitly attached to the
                assistant. If provided along with hierarchy_node_ids, documents
                matching EITHER criteria will be retrieved (OR logic).
            hierarchy_node_ids: Hierarchy node IDs (folders/spaces) attached to
                the assistant. Matches chunks where ancestor_hierarchy_node_ids
                contains any of these values.

        Returns:
            A list of filters to be passed into the "filter" key of a search
                query.
        """

        def _get_acl_visibility_filter(
            access_control_list: list[str],
        ) -> dict[str, Any]:
            # Logical OR operator on its elements.
            acl_visibility_filter: dict[str, Any] = {"bool": {"should": []}}
            acl_visibility_filter["bool"]["should"].append(
                {"term": {PUBLIC_FIELD_NAME: {"value": True}}}
            )
            for acl in access_control_list:
                acl_subclause: dict[str, Any] = {
                    "term": {ACCESS_CONTROL_LIST_FIELD_NAME: {"value": acl}}
                }
                acl_visibility_filter["bool"]["should"].append(acl_subclause)
            return acl_visibility_filter

        def _get_source_type_filter(
            source_types: list[DocumentSource],
        ) -> dict[str, Any]:
            # Logical OR operator on its elements.
            source_type_filter: dict[str, Any] = {"bool": {"should": []}}
            for source_type in source_types:
                source_type_filter["bool"]["should"].append(
                    {"term": {SOURCE_TYPE_FIELD_NAME: {"value": source_type.value}}}
                )
            return source_type_filter

        def _get_tag_filter(tags: list[Tag]) -> dict[str, Any]:
            # Logical OR operator on its elements.
            tag_filter: dict[str, Any] = {"bool": {"should": []}}
            for tag in tags:
                # Kind of an abstraction leak, see
                # convert_metadata_dict_to_list_of_strings for why metadata list
                # entries are expected to look this way.
                tag_str = f"{tag.tag_key}{INDEX_SEPARATOR}{tag.tag_value}"
                tag_filter["bool"]["should"].append(
                    {"term": {METADATA_LIST_FIELD_NAME: {"value": tag_str}}}
                )
            return tag_filter

        def _get_document_set_filter(document_sets: list[str]) -> dict[str, Any]:
            # Logical OR operator on its elements.
            document_set_filter: dict[str, Any] = {"bool": {"should": []}}
            for document_set in document_sets:
                document_set_filter["bool"]["should"].append(
                    {"term": {DOCUMENT_SETS_FIELD_NAME: {"value": document_set}}}
                )
            return document_set_filter

        def _get_user_file_id_filter(user_file_ids: list[UUID]) -> dict[str, Any]:
            # Logical OR operator on its elements.
            user_file_id_filter: dict[str, Any] = {"bool": {"should": []}}
            for user_file_id in user_file_ids:
                user_file_id_filter["bool"]["should"].append(
                    {"term": {DOCUMENT_ID_FIELD_NAME: {"value": str(user_file_id)}}}
                )
            return user_file_id_filter

        def _get_user_project_filter(project_id: int) -> dict[str, Any]:
            # Logical OR operator on its elements.
            user_project_filter: dict[str, Any] = {"bool": {"should": []}}
            user_project_filter["bool"]["should"].append(
                {"term": {USER_PROJECTS_FIELD_NAME: {"value": project_id}}}
            )
            return user_project_filter

        def _get_time_cutoff_filter(time_cutoff: datetime) -> dict[str, Any]:
            # Convert to UTC if not already so the cutoff is comparable to the
            # document data.
            time_cutoff = set_or_convert_timezone_to_utc(time_cutoff)
            # Logical OR operator on its elements.
            time_cutoff_filter: dict[str, Any] = {"bool": {"should": []}}
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
        ) -> dict[str, Any]:
            """Filter for documents explicitly attached to an assistant."""
            # Logical OR operator on its elements.
            doc_id_filter: dict[str, Any] = {"bool": {"should": []}}
            for doc_id in doc_ids:
                doc_id_filter["bool"]["should"].append(
                    {"term": {DOCUMENT_ID_FIELD_NAME: {"value": doc_id}}}
                )
            return doc_id_filter

        def _get_hierarchy_node_filter(
            node_ids: list[int],
        ) -> dict[str, Any]:
            """Filter for chunks whose ancestors include any of the given hierarchy nodes.

            Uses a terms query to check if ancestor_hierarchy_node_ids contains
            any of the specified node IDs.
            """
            return {"terms": {ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME: node_ids}}

        def _get_assistant_knowledge_filter(
            attached_doc_ids: list[str] | None,
            node_ids: list[int] | None,
            file_ids: list[UUID] | None,
            document_sets: list[str] | None,
        ) -> dict[str, Any]:
            """Combined filter for assistant knowledge.

            When an assistant has attached knowledge, search should be scoped to:
            - Documents explicitly attached (by document ID), OR
            - Documents under attached hierarchy nodes (by ancestor node IDs), OR
            - User-uploaded files attached to the assistant, OR
            - Documents in the assistant's document sets (if any)
            """
            knowledge_filter: dict[str, Any] = {
                "bool": {"should": [], "minimum_should_match": 1}
            }
            if attached_doc_ids:
                knowledge_filter["bool"]["should"].append(
                    _get_attached_document_id_filter(attached_doc_ids)
                )
            if node_ids:
                knowledge_filter["bool"]["should"].append(
                    _get_hierarchy_node_filter(node_ids)
                )
            if file_ids:
                knowledge_filter["bool"]["should"].append(
                    _get_user_file_id_filter(file_ids)
                )
            if document_sets:
                knowledge_filter["bool"]["should"].append(
                    _get_document_set_filter(document_sets)
                )
            return knowledge_filter

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

        # Check if this is an assistant knowledge search (has any assistant-scoped knowledge)
        has_assistant_knowledge = (
            attached_document_ids
            or hierarchy_node_ids
            or user_file_ids
            or document_sets
        )

        if has_assistant_knowledge:
            # If assistant has attached knowledge, scope search to that knowledge.
            # Document sets are included in the OR filter so directly attached
            # docs are always findable even if not in the document sets.
            filter_clauses.append(
                _get_assistant_knowledge_filter(
                    attached_document_ids,
                    hierarchy_node_ids,
                    user_file_ids,
                    document_sets,
                )
            )
        elif user_file_ids:
            # Fallback for non-assistant user file searches (e.g., project searches)
            # If at least one user file ID is provided, the caller will only
            # retrieve documents where the document ID is in this input list of
            # file IDs.
            filter_clauses.append(_get_user_file_id_filter(user_file_ids))

        if project_id is not None:
            # If a project ID is provided, the caller will only retrieve
            # documents where the project ID provided here is present in the
            # document's user projects list.
            filter_clauses.append(_get_user_project_filter(project_id))

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
            # WARNING: If user_file_ids has elements and if none of them are
            # document_id, no matches will be retrieved.
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
