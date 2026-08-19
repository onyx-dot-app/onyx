MAX_IN_MEMORY_SIZE = 30 * 1024 * 1024  # 30MB
STANDARD_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks

# Marks a blob a content-free chat turn produced, so cleanup can find it by the
# record itself rather than by anything that can expire.
INCOGNITO_SESSION_METADATA_KEY = "incognito_session_id"
