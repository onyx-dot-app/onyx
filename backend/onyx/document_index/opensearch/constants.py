# Size of the dynamic list used to consider elements during kNN graph creation.
# Higher values improve search quality but increase indexing time. Values
# typically range between 100 - 512.
EF_CONSTRUCTION = 256
# Number of bi-directional links per element. Higher values improve search
# quality but increase memory footprint. Values typically range between 12 - 48.
M = 32  # Increased for better accuracy.

DEFAULT_MAX_CHUNK_SIZE = 512

TITLE_VECTOR_WEIGHT = 0.05
TITLE_KEYWORD_WEIGHT = 0.05
CONTENT_VECTOR_WEIGHT = 0.50  # Increased to favor semantic search.
CONTENT_KEYWORD_WEIGHT = 0.35  # Decreased to favor semantic search.
CONTENT_PHRASE_WEIGHT = 0.05  # Phrase matching weight

# Number of vectors to examine for top k neighbors for the HNSW method. Values
# typically range between 100 - 200.
EF_SEARCH = 200
