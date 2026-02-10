import os

PROMPTS_YAML = "./onyx/seeding/prompts.yaml"
PERSONAS_YAML = "./onyx/seeding/personas.yaml"
NUM_RETURNED_HITS = 50

# May be less depending on model
MAX_CHUNKS_FED_TO_CHAT = int(os.environ.get("MAX_CHUNKS_FED_TO_CHAT") or 25)

# 1 / (1 + DOC_TIME_DECAY * doc-age-in-years), set to 0 to have no decay
# Capped in Vespa at 0.5
DOC_TIME_DECAY = float(
    os.environ.get("DOC_TIME_DECAY") or 0.5  # Hits limit at 2 years by default
)
BASE_RECENCY_DECAY = 0.5
FAVOR_RECENT_DECAY_MULTIPLIER = 2.0
# For the highest matching base size chunk, how many chunks above and below do we pull in by default
# Note this is not in any of the deployment configs yet
# Currently only applies to search flow not chat
CONTEXT_CHUNKS_ABOVE = int(os.environ.get("CONTEXT_CHUNKS_ABOVE") or 1)
CONTEXT_CHUNKS_BELOW = int(os.environ.get("CONTEXT_CHUNKS_BELOW") or 1)
# Fairly long but this is to account for edge cases where the LLM pauses for much longer than usual
# The alternative is to fail the request completely so this is intended to be fairly lenient.
LLM_SOCKET_READ_TIMEOUT = int(
    os.environ.get("LLM_SOCKET_READ_TIMEOUT") or "60"
)  # 60 seconds
# Weighting factor between Vector and Keyword Search, 1 for completely vector search
HYBRID_ALPHA = max(0, min(1, float(os.environ.get("HYBRID_ALPHA") or 0.5)))
HYBRID_ALPHA_KEYWORD = max(
    0, min(1, float(os.environ.get("HYBRID_ALPHA_KEYWORD") or 0.4))
)
# Weighting factor between Title and Content of documents during search, 1 for completely
# Title based. Default heavily favors Content because Title is also included at the top of
# Content. This is to avoid cases where the Content is very relevant but it may not be clear
# if the title is separated out. Title is most of a "boost" than a separate field.
TITLE_CONTENT_RATIO = max(
    0, min(1, float(os.environ.get("TITLE_CONTENT_RATIO") or 0.10))
)

# Stops streaming answers back to the UI if this pattern is seen:
STOP_STREAM_PAT = os.environ.get("STOP_STREAM_PAT") or None

# Set this to "true" to hard delete chats
# This will make chats unviewable by admins after a user deletes them
# As opposed to soft deleting them, which just hides them from non-admin users
HARD_DELETE_CHATS = os.environ.get("HARD_DELETE_CHATS", "").lower() == "true"

# Internet Search
NUM_INTERNET_SEARCH_RESULTS = int(os.environ.get("NUM_INTERNET_SEARCH_RESULTS") or 10)
NUM_INTERNET_SEARCH_CHUNKS = int(os.environ.get("NUM_INTERNET_SEARCH_CHUNKS") or 50)

VESPA_SEARCHER_THREADS = int(os.environ.get("VESPA_SEARCHER_THREADS") or 2)

# Whether or not to use the semantic & keyword search expansions for Basic Search
USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH = (
    os.environ.get("USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH", "false").lower()
    == "true"
)

# Chat History Compression
# Trigger compression when history exceeds this ratio of available context window
COMPRESSION_TRIGGER_RATIO = float(os.environ.get("COMPRESSION_TRIGGER_RATIO", "0.75"))

SKIP_DEEP_RESEARCH_CLARIFICATION = (
    os.environ.get("SKIP_DEEP_RESEARCH_CLARIFICATION", "false").lower() == "true"
)
