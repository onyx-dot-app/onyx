# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
import os
from enum import Enum

from onyx.configs.app_configs import (
    OPENSEARCH_OVERRIDE_DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES,
)


DEFAULT_MAX_CHUNK_SIZE = 512

# Size of the dynamic list used to consider elements during kNN graph creation.
# Higher values improve search quality but increase indexing time. Values
# typically range between 100 - 512.
EF_CONSTRUCTION = 256
# Number of bi-directional links per element. Higher values improve search
# quality but increase memory footprint. Values typically range between 12 - 48.
M = 32  # Set relatively high for better accuracy.

# When performing hybrid search, we need to consider more candidates than the
# number of results to be returned. This is because the scoring is hybrid and
# the results are reordered due to the hybrid scoring. Higher = more candidates
# for hybrid fusion = better retrieval accuracy, but results in more computation
# per query. Imagine a simple case with a single keyword query and a single
# vector query and we want 10 final docs. If we only fetch 10 candidates from
# each of keyword and vector, they would have to have perfect overlap to get a
# good hybrid ranking for the 10 results. If we fetch 1000 candidates from each,
# we have a much higher chance of all 10 of the final desired docs showing up
# and getting scored. In worse situations, the final 10 docs don't even show up
# as the final 10 (worse than just a miss at the reranking step).
DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES = (
    OPENSEARCH_OVERRIDE_DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES
    if OPENSEARCH_OVERRIDE_DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES > 0
    else 750
)

# Number of vectors to examine to decide the top k neighbors for the HNSW
# method.
# NOTE: "When creating a search query, you must specify k. If you provide both k
# and ef_search, then the larger value is passed to the engine. If ef_search is
# larger than k, you can provide the size parameter to limit the final number of
# results to k." from
# https://docs.opensearch.org/latest/query-dsl/specialized/k-nn/index/#ef_search
EF_SEARCH = DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES


class HybridSearchSubqueryConfiguration(Enum):
    TITLE_VECTOR_CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD = 1
    CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD = 2


HYBRID_SEARCH_SUBQUERY_CONFIGURATION: HybridSearchSubqueryConfiguration = (
    HybridSearchSubqueryConfiguration(
        int(os.environ.get("HYBRID_SEARCH_SUBQUERY_CONFIGURATION"))
    )
    if int(os.environ.get("HYBRID_SEARCH_SUBQUERY_CONFIGURATION", -1))
    in {c.value for c in HybridSearchSubqueryConfiguration}
    else HybridSearchSubqueryConfiguration.CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
)
