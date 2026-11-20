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
# Published files (FileOrigin.CHAT_ARTIFACT) have the ID
# `<prefix><root chat session ID>-<hex>`, so a chat delete finds them also when
# no message lists them. No "/": the ID is a path segment of the download route.
CHAT_ARTIFACT_FILE_PREFIX = "chat-artifact-"
