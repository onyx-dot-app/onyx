import os

# Used for logging
SLACK_CHANNEL_ID = "channel_id"

MODEL_SERVER_HOST = os.environ.get("MODEL_SERVER_HOST") or "localhost"
MODEL_SERVER_ALLOWED_HOST = os.environ.get("MODEL_SERVER_HOST") or "0.0.0.0"
MODEL_SERVER_PORT = int(os.environ.get("MODEL_SERVER_PORT") or "9000")
# Model server for indexing should use a separate one to not allow indexing to introduce delay
# for inference
INDEXING_MODEL_SERVER_HOST = (
    os.environ.get("INDEXING_MODEL_SERVER_HOST") or MODEL_SERVER_HOST
)
INDEXING_MODEL_SERVER_PORT = int(
    os.environ.get("INDEXING_MODEL_SERVER_PORT") or MODEL_SERVER_PORT
)

# Danswer custom Deep Learning Models
INTENT_MODEL_VERSION = "danswer/hybrid-intent-token-classifier"
INTENT_MODEL_TAG = "v1.0.3"

# Bi-Encoder, other details
DOC_EMBEDDING_CONTEXT_SIZE = 512

# Used to distinguish alternative indices
ALT_INDEX_SUFFIX = "__danswer_alt_index"

# Used for loading defaults for automatic deployments and dev flows
# For local, use: mixedbread-ai/mxbai-rerank-xsmall-v1
DEFAULT_CROSS_ENCODER_MODEL_NAME = (
    os.environ.get("DEFAULT_CROSS_ENCODER_MODEL_NAME") or None
)
DEFAULT_CROSS_ENCODER_API_KEY = os.environ.get("DEFAULT_CROSS_ENCODER_API_KEY") or None
DEFAULT_CROSS_ENCODER_PROVIDER_TYPE = (
    os.environ.get("DEFAULT_CROSS_ENCODER_PROVIDER_TYPE") or None
)
DISABLE_RERANK_FOR_STREAMING = (
    os.environ.get("DISABLE_RERANK_FOR_STREAMING", "").lower() == "true"
)

# This controls the minimum number of pytorch "threads" to allocate to the embedding
# model. If torch finds more threads on its own, this value is not used.
MIN_THREADS_ML_MODELS = int(os.environ.get("MIN_THREADS_ML_MODELS") or 1)

# Model server that has indexing only set will throw exception if used for reranking
# or intent classification
INDEXING_ONLY = os.environ.get("INDEXING_ONLY", "").lower() == "true"

# The process needs to have this for the log file to write to
# otherwise, it will not create additional log files
LOG_FILE_NAME = os.environ.get("LOG_FILE_NAME") or "danswer"

# Enable generating persistent log files for local dev environments
DEV_LOGGING_ENABLED = os.environ.get("DEV_LOGGING_ENABLED", "").lower() == "true"
# notset, debug, info, notice, warning, error, or critical
LOG_LEVEL = os.environ.get("LOG_LEVEL", "notice")
