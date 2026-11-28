MAX_IN_MEMORY_SIZE = 30 * 1024 * 1024  # 30MB
STANDARD_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks

# Marks a blob a content-free chat turn produced, so cleanup can find it by the
# record itself rather than by anything that can expire.
INCOGNITO_SESSION_METADATA_KEY = "incognito_session_id"

# The sha256 of a connector file's bytes, recorded at upload.
CONTENT_SHA256_METADATA_KEY = "content_sha256"
# Marks a file uploaded during a connector edit. Apply removes the mark; the
# cleanup task deletes marked files after they expire.
STAGED_FOR_CC_PAIR_METADATA_KEY = "staged_for_cc_pair_id"

AGENT_CHECKPOINT_FILE_PREFIX = "agent-checkpoint/"

# The cached text of a published file version is ARTIFACT_TEXT_FILE_PREFIX +
# its file_id (utils.py:get_or_extract_artifact_text).
ARTIFACT_TEXT_FILE_PREFIX = "artifact_text_"
# A larger published file has no text, and the stored text of one file stops
# at ARTIFACT_TEXT_MAX_CHARS.
ARTIFACT_TEXT_MAX_FILE_BYTES = 50 << 20
ARTIFACT_TEXT_MAX_CHARS = 10_000_000
