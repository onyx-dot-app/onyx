import os
from enum import Enum

from pydantic import BaseModel

from onyx.db.enums import VectorQuantization

# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
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


class LuceneScalarQuantization(BaseModel):
    """Lucene "sq" encoder settings for one VectorQuantization level.

    See https://docs.opensearch.org/latest/vector-search/optimizing-storage/lucene-scalar-quantization/
    """

    model_config = {"frozen": True}

    # Bits per vector dimension. Always set this explicitly: on OpenSearch 3.6+
    # an "sq" encoder without bits defaults to 1 bit.
    bits: int
    # A k-NN query on a quantized field gets oversample_factor * k candidates
    # with the quantized vectors, then rescores them with the full-precision
    # vectors. OpenSearch rescores by default only in on_disk mode, so our
    # queries must ask for it. The values are the OpenSearch defaults for 4x
    # (7-bit) and Lucene 32x (1-bit) compression.
    rescore_oversample_factor: float
    # The first (major, minor) OpenSearch version that accepts these bits.
    min_opensearch_version: tuple[int, int]


# VectorQuantization.NONE has no entry.
LUCENE_SCALAR_QUANTIZATION: dict[VectorQuantization, LuceneScalarQuantization] = {
    VectorQuantization.SCALAR_7_BIT: LuceneScalarQuantization(
        bits=7, rescore_oversample_factor=1.0, min_opensearch_version=(2, 16)
    ),
    VectorQuantization.SCALAR_1_BIT: LuceneScalarQuantization(
        bits=1, rescore_oversample_factor=2.0, min_opensearch_version=(3, 6)
    ),
}


class OpenSearchAuthMethod(str, Enum):
    """Authentication method for connecting to OpenSearch.

    BASIC uses HTTP basic auth (username/password); the only option for
    self-hosted / docker-compose OpenSearch. IAM uses AWS SigV4 request signing
    and is only valid against an AWS managed domain whose fine-grained access
    control master is an IAM ARN.
    """

    BASIC = "basic"
    IAM = "iam"


class OpenSearchSearchType(str, Enum):
    """Search type label used for Prometheus metrics."""

    HYBRID = "hybrid"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    RANDOM = "random"
    DOC_ID_RETRIEVAL = "doc_id_retrieval"
    CC_PAIR_ACCESS_SHADOW = "cc_pair_access_shadow"
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

RESOURCE_CHECK_INTERVAL_SECONDS = 5 * 60
RESOURCE_CHECK_TIMEOUT_SECONDS = 3
