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
# Chosen by testing on real documents: gpt-6-luna matched the best pass rate at
# the lowest price. The fallback is as cheap, from another provider.
SQ_WRITING_OPENAI_MODEL = os.environ.get("SQ_WRITING_OPENAI_MODEL") or "gpt-6-luna"
SQ_WRITING_ANTHROPIC_MODEL = (
    os.environ.get("SQ_WRITING_ANTHROPIC_MODEL") or "claude-haiku-5-5"
)
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

# When a pool run is worth it. Running low: fewer usable questions than this.
SQ_POOL_SHORT = 12
# New material: at least this many new documents since the last run, while the
# pool has room (fewer than SQ_POOL_MAX questions).
SQ_MIN_NEW_DOCS = 20
# No run with fewer documents than this that are not yet in the pool.
SQ_MIN_CANDIDATE_DOCS = 5
# Minimum minutes since the last run: when running low, and for new material,
# so a connector that indexes for hours does not use every run at once.
SQ_SHORT_GAP_MIN = 10
SQ_GROWTH_GAP_MIN = 60
# A safety limit on pool runs per SQ_RUN_WINDOW_HOURS.
SQ_MAX_POOL_RUNS_PER_DAY = 5
# A question is not shown, and does not count as usable, after this age.
SQ_QUESTION_MAX_AGE_DAYS = 7

# Top-ups for one person: at most this many per SQ_RUN_WINDOW_HOURS, and this
# many minutes apart.
SQ_TOPUPS_PER_USER_PER_DAY = 5
SQ_TOPUP_GAP_MIN = 10

# Delay before a new-material run, so a large connector does not request a run
# per batch. Other runs start at once.
SQ_GROWTH_DELAY_S = 600
# A queued task expires this long after it was due, and the queued flag lives
# as long as the task can wait, so a stale flag cannot block runs.
SQ_TASK_EXPIRES_S = 1800
# Lease of the pool lock. It expires only on Redis; on Postgres the lock is
# held until released or the session closes. Celery time limits do not apply
# in thread pools, so a run must keep its own time budget well below this.
SQ_POOL_LOCK_HELD_S = 120.0
# How long a deletion waits for a running pool run to finish with the pool.
SQ_POOL_LOCK_WAIT_S = 5.0

# A run's own time budget: Celery time limits do not apply in thread pools.
# Each model call has its own timeout too.
SQ_RUN_BUDGET_S = 60.0
# Retries of a failed run, and the wait before each.
SQ_RUN_RETRIES = 2
SQ_RUN_RETRY_DELAY_S = 30
# A run does not save the pool when less than this many seconds of the lock's
# lease are left: the lease could expire before the save finishes.
SQ_SAVE_MARGIN_S = 30.0
# A top-up that finds a run holding the pool tries again after this long.
SQ_LOCK_BUSY_RETRY_S = 60
# A pool run that finds the pool locked tries again after this long.
SQ_POOL_BUSY_RETRY_S = 120
