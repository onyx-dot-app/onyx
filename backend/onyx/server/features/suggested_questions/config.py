# Questions kept in a company's pool after each merge.
SQ_POOL_MAX = 40

# A person counts as active if they opened the chat within this many days.
SQ_ACTIVE_DAYS = 7

# Clicked question ids kept per person. Pool ids rotate, so older ones only
# take space.
SQ_USED_IDS_MAX = 200

# Pool runs count against the daily limit inside this window.
SQ_RUN_WINDOW_HOURS = 24

# Lock around the read-modify-write of one person's record.
SQ_USER_RECORD_LOCK_TIMEOUT_S = 5.0

# Newest documents everyone can see, per run.
SQ_SHARED_DOCS = 30
# Newest documents only that person (or a few people) can see, per person.
SQ_PRIVATE_DOCS_PER_USER = 12
# Chunks kept per document, and in all, for the triage step.
SQ_CHUNKS_PER_DOC = 3
SQ_TRIAGE_CHUNKS_MAX = 300

# Cheap rules that drop chunks with nothing to ask about before triage.
SQ_MIN_CHUNK_CHARS = 300
SQ_MIN_LETTER_RATIO = 0.6
SQ_MAX_LINK_RATIO = 0.3
SQ_MAX_LINE_REPEATS = 2
SQ_MAX_WORD_OVERLAP = 0.5
