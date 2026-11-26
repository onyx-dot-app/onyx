import os

# The shared shelf: questions about company-wide documents, one per company.
SQ_SHARED_SHELF = 20
# The private shelf: questions about one person's own documents.
SQ_PRIVATE_SHELF = 8
# A top-up runs only while the person has this many usable private questions
# or fewer. The ones over the 4 shown cover a refill that fails.
SQ_PRIVATE_REFILL_AT = 6
# A person is short of shared questions with this many unused ones or fewer.
SQ_SHARED_REFRESH_AT = 4
# Questions shown to a person at a time.
SQ_SHOWN = 4
# After a chat open asks for a run, the page shows "preparing" this long.
SQ_PREPARING_S = 120

# A person counts as active if they opened the chat within this many days.
SQ_ACTIVE_DAYS = 7

# Clicked question ids kept per person. Pool ids rotate, so older ones only
# take space.
SQ_USED_IDS_MAX = 200
# Largest question id a click may store. Ids are 32 hex characters.
SQ_QUESTION_ID_MAX_BYTES = 64

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
# Chunks kept per document for the writing call.
SQ_CHUNKS_PER_DOC = 3

# Cheap rules that drop chunks with nothing to ask about before the writing
# call.
SQ_MIN_CHUNK_CHARS = 300
SQ_MIN_LETTER_RATIO = 0.6
SQ_MAX_LINK_RATIO = 0.3
SQ_MAX_LINE_REPEATS = 2
SQ_MAX_WORD_OVERLAP = 0.5

# The writing call: a small model, fixed here.
# Chosen by testing on real documents: gpt-6-luna matched the best pass rate at
# the lowest price. The fallback is as cheap, from another provider.
SQ_WRITING_OPENAI_MODEL = os.environ.get("SQ_WRITING_OPENAI_MODEL") or "gpt-6-luna"
SQ_WRITING_ANTHROPIC_MODEL = (
    os.environ.get("SQ_WRITING_ANTHROPIC_MODEL") or "claude-haiku-5-5"
)
# The thinking tokens count toward this too.
SQ_WRITING_MAX_TOKENS = 4000
# Seconds for one writing call.
SQ_LLM_TIMEOUT_S = 30.0
# Passages a run sends to the writing calls, and characters per passage
# (about 200 tokens). The calls pick the passages worth a question, so they
# read all the chunks of a pool run's shared documents.
SQ_PASSAGES_MAX = SQ_SHARED_DOCS * SQ_CHUNKS_PER_DOC
SQ_PASSAGE_CHARS = 800
# Writing calls a run makes at the same time, each on its share of the
# documents. Three calls made a run about twice as fast as one, at the same
# cost.
SQ_WRITING_CALLS = 3
# Questions kept from one run, at most one per document.
SQ_QUESTIONS_PER_RUN = 12
SQ_QUESTION_MAX_CHARS = 90

# Search test: keep a question when its document is among the first
# SQ_TOP_K_DOCS distinct documents of a search for SQ_SEARCH_LIMIT chunks.
SQ_TOP_K_DOCS = 3
SQ_SEARCH_LIMIT = 10
# Searches run at the same time. They call the shared model server, so keep
# it small.
SQ_SEARCH_WORKERS = 4

# No pool run with fewer documents than this that have no question yet.
SQ_MIN_CANDIDATE_DOCS = 5
# Minimum minutes between pool runs.
SQ_POOL_RUN_GAP_MIN = 10
# A safety limit on pool runs per SQ_RUN_WINDOW_HOURS.
SQ_MAX_POOL_RUNS_PER_DAY = 5
# A question is not shown, and does not count as usable, after this age.
SQ_QUESTION_MAX_AGE_DAYS = 7

# Top-ups for one person: at most this many per SQ_RUN_WINDOW_HOURS, and this
# many minutes apart.
SQ_TOPUPS_PER_USER_PER_DAY = 5
SQ_TOPUP_GAP_MIN = 10

# A queued task expires this long after it was sent, and the queued flag lives
# as long as the task can wait, so a stale flag cannot block runs.
SQ_TASK_EXPIRES_S = 1800
# Lease of the pool lock. It expires only on Redis; on Postgres the lock is
# held until released or the session closes. Celery time limits do not apply
# in thread pools, so a run must keep its own time budget well below this.
SQ_POOL_LOCK_HELD_S = 120.0

# A run's own time budget: Celery time limits do not apply in thread pools.
# Each model call has its own timeout too.
SQ_RUN_BUDGET_S = 60.0
# Seconds of the budget kept for the search test: the writing calls stop
# waiting this long before the budget ends.
SQ_SEARCH_TEST_RESERVE_S = 10.0
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
