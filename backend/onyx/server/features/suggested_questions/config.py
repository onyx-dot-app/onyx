import os

from onyx.llm.decisions.models import OPENAI_DECISIONS_MODEL_NAME

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
# Chunks read from the start of each document; junk rules then keep up to
# SQ_CHUNKS_PER_DOC of them.
SQ_FETCH_CHUNKS_PER_DOC = 6
# Chunks kept per document, and in all, for the triage step.
SQ_CHUNKS_PER_DOC = 3
SQ_TRIAGE_CHUNKS_MAX = 300

# Cheap rules that drop chunks with nothing to ask about before triage.
SQ_MIN_CHUNK_CHARS = 300
SQ_MIN_LETTER_RATIO = 0.6
SQ_MAX_LINK_RATIO = 0.3
SQ_MAX_LINE_REPEATS = 2
SQ_MAX_WORD_OVERLAP = 0.5

# Triage: a decision model reads a snippet of each chunk before the writing
# call. Models are fixed here, not taken from the admin's decision model.
SQ_TRIAGE_OPENAI_MODEL = (
    os.environ.get("SQ_TRIAGE_OPENAI_MODEL") or OPENAI_DECISIONS_MODEL_NAME
)
SQ_TRIAGE_ZOOM_MODEL = os.environ.get("SQ_TRIAGE_ZOOM_MODEL") or "zoom-decisions-pro"
# Characters of each chunk sent to triage, about 150 tokens.
SQ_TRIAGE_SNIPPET_CHARS = 600
# Chunks per decision request. Each gets 4 questions; a request takes 200.
SQ_TRIAGE_CHUNKS_PER_REQUEST = 50
# Keep a chunk when its usable score (0 to 3) is at least this, and its
# sensitive probability is under the second value: liberal on usefulness,
# strict on sensitivity.
SQ_TRIAGE_MIN_SCORE = 1.0
SQ_TRIAGE_SENSITIVE_MAX = 0.3
# When both decision providers fail, the rules keep only early chunks.
SQ_RULES_MAX_CHUNK_ID = 2
# With fewer documents than this left after triage, keep two chunks per
# document instead of one.
SQ_FEW_DOCUMENTS = 6

# The writing call: a small model, fixed here like the triage models.
SQ_WRITING_OPENAI_MODEL = os.environ.get("SQ_WRITING_OPENAI_MODEL") or "gpt-6-luna"
SQ_WRITING_MAX_TOKENS = 1200
# Seconds for one writing call. Triage uses the decision client default, also 30.
SQ_LLM_TIMEOUT_S = 30.0
# Passages sent to the writing call, and characters per passage (about 350
# tokens).
SQ_PASSAGES_MAX = 20
SQ_PASSAGE_CHARS = 1400
# Questions kept from one writing call, in all and per passage.
SQ_QUESTIONS_PER_RUN = 12
SQ_QUESTIONS_PER_PASSAGE = 2
SQ_QUESTION_MAX_CHARS = 90

# Search test: keep a question when its document is among the first
# SQ_TOP_K_DOCS distinct documents of a search for SQ_SEARCH_LIMIT chunks.
SQ_TOP_K_DOCS = 3
SQ_SEARCH_LIMIT = 10
# Searches, and triage requests, run at the same time. Both call shared
# services (the model server, the decision provider), so keep it small.
SQ_SEARCH_WORKERS = 4
SQ_TRIAGE_WORKERS = 4
