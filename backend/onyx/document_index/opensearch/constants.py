# Size of the dynamic list used to consider elements during kNN graph creation.
# Higher values improve search quality but increase indexing time. Values
# typically range between 100 - 512.
EF_CONSTRUCTION = 256
# Number of bi-directional links per element. Higher values improve search
# quality but increase memory footprint. Values typically range between 12 - 48.
M = 32  # Increased for better accuracy.

# Default value for the maximum number of tokens a chunk can hold, if none is
# specified when creating an index.
DEFAULT_MAX_CHUNK_SIZE = 512

# Number of vectors to examine for top k neighbors for the HNSW method.
EF_SEARCH = 256

# The default number of neighbors to consider for knn vector similarity search.
# We need this higher than the number of results because the scoring is hybrid.
# If there is only 1 query, setting k equal to the number of results is enough,
# but since there is heavy reordering due to hybrid scoring, we need to set k higher.
DEFAULT_K_NUM_CANDIDATES = 50  # TODO likely need to bump this way higher

# Default weights to use for hybrid search normalization. These values should
# sum to 1. Order matches hybrid sub-queries: title vector, title keyword,
# content vector, content keyword (keyword + phrase combined).
SEARCH_TITLE_VECTOR_WEIGHT = 0.1
SEARCH_TITLE_KEYWORD_WEIGHT = 0.1
SEARCH_CONTENT_VECTOR_WEIGHT = 0.4
SEARCH_CONTENT_KEYWORD_WEIGHT = 0.4
