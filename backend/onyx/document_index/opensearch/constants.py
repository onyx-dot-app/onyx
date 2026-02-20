# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
DEFAULT_MAX_CHUNK_SIZE = 512

# Size of the dynamic list used to consider elements during kNN graph creation.
# Higher values improve search quality but increase indexing time. Values
# typically range between 100 - 512.
EF_CONSTRUCTION = 256
# Number of bi-directional links per element. Higher values improve search
# quality but increase memory footprint. Values typically range between 12 - 48.
M = 32  # Set relatively high for better accuracy.

# When performing hybrid search, we need to consider more candidates than the number of results to be returned.
# This is because the scoring is hybrid and the results are reordered due to the hybrid scoring.
# Higher = more candidates for hybrid fusion = better retrieval accuracy, but results in more computation per query.
# Imagine a simple case with a single keyword query and a single vector query and we want 10 final docs.
# If we only fetch 10 candidates from each of keyword and vector, they would have to have perfect overlap to get a good hybrid
# ranking for the 10 results. If we fetch 1000 candidates from each, we have a much higher chance of all 10 of the final desired
# docs showing up and getting scored. In worse situations, the final 10 docs don't even show up as the final 10 (worse than just
# a miss at the reranking step).
DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES = 750

# Number of vectors to examine for top k neighbors for the HNSW method.
EF_SEARCH = DEFAULT_NUM_HYBRID_SEARCH_CANDIDATES

# Since the titles are included in the contents, they are heavily downweighted as they act as a boost
# rather than an independent scoring component.
SEARCH_TITLE_VECTOR_WEIGHT = 0.1
SEARCH_CONTENT_VECTOR_WEIGHT = 0.45
# Single keyword weight for both title and content (merged from former title keyword + content keyword).
SEARCH_KEYWORD_WEIGHT = 0.45

# NOTE: it is critical that the order of these weights matches the order of the sub-queries in the hybrid search.
HYBRID_SEARCH_NORMALIZATION_WEIGHTS = [
    SEARCH_TITLE_VECTOR_WEIGHT,
    SEARCH_CONTENT_VECTOR_WEIGHT,
    SEARCH_KEYWORD_WEIGHT,
]

assert sum(HYBRID_SEARCH_NORMALIZATION_WEIGHTS) == 1.0
