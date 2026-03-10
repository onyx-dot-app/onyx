import os


def _read_int_env(var_name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.environ.get(var_name)
    if raw_value in (None, ""):
        return default
    try:
        return max(minimum, int(raw_value))
    except ValueError:
        return default


def _read_float_env(var_name: str, default: float, minimum: float = 0.0) -> float:
    raw_value = os.environ.get(var_name)
    if raw_value in (None, ""):
        return default
    try:
        return max(minimum, float(raw_value))
    except ValueError:
        return default


# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
DEFAULT_MAX_CHUNK_SIZE = 512

# Size of the dynamic list used to consider elements during kNN graph creation.
# Higher values improve search quality but increase indexing time. Values
# typically range between 100 - 512.
EF_CONSTRUCTION = _read_int_env("OPENSEARCH_EF_CONSTRUCTION", 256)
# Number of bi-directional links per element. Higher values improve search
# quality but increase memory footprint. Values typically range between 12 - 48.
M = _read_int_env("OPENSEARCH_HNSW_M", 32)  # Set relatively high for better accuracy.

# When performing hybrid search, we need to consider more candidates than the number of results to be returned.
# This is because the scoring is hybrid and the results are reordered due to the hybrid scoring.
# Higher = more candidates for hybrid fusion = better retrieval accuracy, but results in more computation per query.
# Imagine a simple case with a single keyword query and a single vector query and we want 10 final docs.
# If we only fetch 10 candidates from each of keyword and vector, they would have to have perfect overlap to get a good hybrid
# ranking for the 10 results. If we fetch 1000 candidates from each, we have a much higher chance of all 10 of the final desired
# docs showing up and getting scored. In worse situations, the final 10 docs don't even show up as the final 10 (worse than just
# a miss at the reranking step).
DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES = _read_int_env(
    "OPENSEARCH_HYBRID_NUM_CANDIDATES", 750
)

# Number of vectors to examine for top k neighbors for the HNSW method.
EF_SEARCH = _read_int_env("OPENSEARCH_EF_SEARCH", DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES)

# Hybrid-specific tuning knobs. Keep defaults aligned with existing behavior.
HYBRID_SEARCH_PAGINATION_DEPTH = _read_int_env(
    "OPENSEARCH_HYBRID_PAGINATION_DEPTH",
    DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES,
)
HYBRID_SEARCH_TITLE_VECTOR_CANDIDATES = _read_int_env(
    "OPENSEARCH_HYBRID_TITLE_VECTOR_CANDIDATES",
    DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES,
)
HYBRID_SEARCH_CONTENT_VECTOR_CANDIDATES = _read_int_env(
    "OPENSEARCH_HYBRID_CONTENT_VECTOR_CANDIDATES",
    DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES,
)

# Since the titles are included in the contents, they are heavily downweighted as they act as a boost
# rather than an independent scoring component.
SEARCH_TITLE_VECTOR_WEIGHT = _read_float_env(
    "OPENSEARCH_HYBRID_TITLE_VECTOR_WEIGHT", 0.1
)
SEARCH_CONTENT_VECTOR_WEIGHT = _read_float_env(
    "OPENSEARCH_HYBRID_CONTENT_VECTOR_WEIGHT", 0.45
)
# Single keyword weight for both title and content (merged from former title keyword + content keyword).
SEARCH_KEYWORD_WEIGHT = _read_float_env("OPENSEARCH_HYBRID_KEYWORD_WEIGHT", 0.45)

# Keyword query tuning knobs.
TITLE_MATCH_BOOST = _read_float_env("OPENSEARCH_TITLE_MATCH_BOOST", 0.1)
TITLE_MATCH_PHRASE_BOOST = _read_float_env("OPENSEARCH_TITLE_MATCH_PHRASE_BOOST", 0.2)
CONTENT_MATCH_BOOST = _read_float_env("OPENSEARCH_CONTENT_MATCH_BOOST", 1.0)
CONTENT_MATCH_PHRASE_BOOST = _read_float_env(
    "OPENSEARCH_CONTENT_MATCH_PHRASE_BOOST", 1.5
)
MATCH_PHRASE_SLOP = _read_int_env("OPENSEARCH_MATCH_PHRASE_SLOP", 1, minimum=0)

# Highlight tuning knobs.
HIGHLIGHT_FRAGMENT_SIZE = _read_int_env("OPENSEARCH_HIGHLIGHT_FRAGMENT_SIZE", 100)
HIGHLIGHT_NUM_FRAGMENTS = _read_int_env("OPENSEARCH_HIGHLIGHT_NUM_FRAGMENTS", 4)

# NOTE: it is critical that the order of these weights matches the order of the sub-queries in the hybrid search.
_raw_weights = [
    SEARCH_TITLE_VECTOR_WEIGHT,
    SEARCH_CONTENT_VECTOR_WEIGHT,
    SEARCH_KEYWORD_WEIGHT,
]
_weight_sum = sum(_raw_weights)
if _weight_sum <= 0:
    HYBRID_SEARCH_NORMALIZATION_WEIGHTS = [0.1, 0.45, 0.45]
else:
    HYBRID_SEARCH_NORMALIZATION_WEIGHTS = [
        weight / _weight_sum for weight in _raw_weights
    ]
