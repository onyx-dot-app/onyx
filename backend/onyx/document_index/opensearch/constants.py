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

# Number of vectors to examine for top k neighbors for the HNSW method. Values
# typically range between 100 - 200.
EF_SEARCH = 200

# Default weights to use for hybrid search normalization. These values should
# sum to 1.
SEARCH_TITLE_VECTOR_WEIGHT = 0.05
SEARCH_TITLE_KEYWORD_WEIGHT = 0.05
SEARCH_CONTENT_VECTOR_WEIGHT = 0.50  # Increased to favor semantic search.
SEARCH_CONTENT_KEYWORD_WEIGHT = 0.35  # Decreased to favor semantic search.
SEARCH_CONTENT_PHRASE_WEIGHT = 0.05
