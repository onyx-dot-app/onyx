# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
import os
from enum import Enum


DEFAULT_MAX_CHUNK_SIZE = 512


# By default OpenSearch will only return a maximum of this many results in a
# given search. This value is configurable in the index settings.
DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW = 10_000


# For documents which do not have a value for LAST_UPDATED_FIELD_NAME, we assume
# that the document was last updated this many days ago for the purpose of time
# cutoff filtering during retrieval.
ASSUMED_DOCUMENT_AGE_DAYS = 90


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
# Defaults to 500 for now. Initially this defaulted to 750 but we were seeing
# poor search performance; bumped from 100 to 500 to improve recall.
DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES = int(
    os.environ.get("DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES", 500)
)

# Number of vectors to examine to decide the top k neighbors for the HNSW
# method.
# NOTE: "When creating a search query, you must specify k. If you provide both k
# and ef_search, then the larger value is passed to the engine. If ef_search is
# larger than k, you can provide the size parameter to limit the final number of
# results to k." from
# https://docs.opensearch.org/latest/query-dsl/specialized/k-nn/index/#ef_search
EF_SEARCH = DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES


class OpenSearchSearchType(str, Enum):
    """Search type label used for Prometheus metrics."""

    HYBRID = "hybrid"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    RANDOM = "random"
    ID_RETRIEVAL = "id_retrieval"
    DOCUMENT_IDS = "document_ids"
    UNKNOWN = "unknown"


class HybridSearchSubqueryConfiguration(Enum):
    TITLE_VECTOR_CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD = 1
    # Current default.
    CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD = 2


# Will raise and block application start if HYBRID_SEARCH_SUBQUERY_CONFIGURATION
# is set but not a valid value. If not set, defaults to
# CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD.
HYBRID_SEARCH_SUBQUERY_CONFIGURATION: HybridSearchSubqueryConfiguration = (
    HybridSearchSubqueryConfiguration(
        int(os.environ["HYBRID_SEARCH_SUBQUERY_CONFIGURATION"])
    )
    if os.environ.get("HYBRID_SEARCH_SUBQUERY_CONFIGURATION", None) is not None
    else HybridSearchSubqueryConfiguration.CONTENT_VECTOR_TITLE_CONTENT_COMBINED_KEYWORD
)


class HybridSearchNormalizationPipeline(Enum):
    # Current default.
    MIN_MAX = 1
    # NOTE: Using z-score normalization is better for hybrid search from a
    # theoretical standpoint. Empirically on a small dataset of up to 10K docs,
    # it's not very different. Likely more impactful at scale.
    # https://opensearch.org/blog/introducing-the-z-score-normalization-technique-for-hybrid-search/
    ZSCORE = 2


# Will raise and block application start if HYBRID_SEARCH_NORMALIZATION_PIPELINE
# is set but not a valid value. If not set, defaults to MIN_MAX.
HYBRID_SEARCH_NORMALIZATION_PIPELINE: HybridSearchNormalizationPipeline = (
    HybridSearchNormalizationPipeline(
        int(os.environ["HYBRID_SEARCH_NORMALIZATION_PIPELINE"])
    )
    if os.environ.get("HYBRID_SEARCH_NORMALIZATION_PIPELINE", None) is not None
    else HybridSearchNormalizationPipeline.MIN_MAX
)
