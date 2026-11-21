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
