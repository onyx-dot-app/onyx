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

# Number of vectors to examine for top k neighbors for the HNSW method.
# Should be >= DEFAULT_K_NUM_CANDIDATES for good recall; higher = better accuracy, slower search.
# Bumped this to 1000, for dataset of low 10,000 docs, did not see improvement in recall.
EF_SEARCH = 256

# The default number of neighbors to consider for knn vector similarity search.
# We need this higher than the number of results because the scoring is hybrid.
# If there is only 1 query, setting k equal to the number of results is enough,
# but since there is heavy reordering due to hybrid scoring, we need to set k higher.
# Higher = more candidates for hybrid fusion = better retrieval accuracy, more query cost.
DEFAULT_K_NUM_CANDIDATES = 50  # TODO likely need to bump this way higher

# Since the titles are included in the contents, they are heavily downweighted as they act as a boost
# rather than an independent scoring component.
SEARCH_TITLE_VECTOR_WEIGHT = 0.1
SEARCH_TITLE_KEYWORD_WEIGHT = 0.1
SEARCH_CONTENT_VECTOR_WEIGHT = 0.4
SEARCH_CONTENT_KEYWORD_WEIGHT = 0.4

# NOTE: it is critical that the order of these weights matches the order of the sub-queries in the hybrid search.
HYBRID_SEARCH_NORMALIZATION_WEIGHTS = [
    SEARCH_TITLE_VECTOR_WEIGHT,
    SEARCH_TITLE_KEYWORD_WEIGHT,
    SEARCH_CONTENT_VECTOR_WEIGHT,
    SEARCH_CONTENT_KEYWORD_WEIGHT,
]

assert sum(HYBRID_SEARCH_NORMALIZATION_WEIGHTS) == 1.0
