VECTOR_DIMENSION = 1024
EF_CONSTRUCTION = 256
M = 32  # Increased for better accuracy

CHUNK_SIZE = 512

OS_INDEX_NAME = "onyx_index"

TITLE_VECTOR_WEIGHT = 0.05
TITLE_KEYWORD_WEIGHT = 0.05
CONTENT_VECTOR_WEIGHT = 0.50  # Increased to favor semantic search
CONTENT_KEYWORD_WEIGHT = 0.35  # Decreased to favor semantic search
CONTENT_PHRASE_WEIGHT = 0.05  # Phrase matching weight


TEST_QUERIES = ["Who were some of the leaders of Anarchism?"]
