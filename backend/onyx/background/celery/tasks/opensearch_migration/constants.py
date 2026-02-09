# Tasks are expected to cease execution and do cleanup after the soft time
# limit. In principle they are also forceably terminated after the hard time
# limit, in practice this does not happen since we use threadpools for Celery
# task execution, and we simple hope that the total task time plus cleanup does
# not exceed this. Therefore tasks should regularly check their timeout and lock
# status. The lock timeout is the maximum time the lock manager (Redis in this
# case) will enforce the lock, independent of what is happening in the task. To
# reduce the chances that a task is still doing work while a lock has expired,
# make the lock timeout well above the task timeouts. In practice we should
# never see locks be held for this long anyway because a task should release the
# lock after its cleanup which happens at most after its soft timeout.

# Constants corresponding to migrate_documents_from_vespa_to_opensearch_task.
MIGRATION_TASK_SOFT_TIME_LIMIT_S = 60 * 5  # 5 minutes.
MIGRATION_TASK_TIME_LIMIT_S = 60 * 6  # 6 minutes.
# The maximum time the lock can be held for. Will automatically be released
# after this time.
MIGRATION_TASK_LOCK_TIMEOUT_S = 60 * 7  # 7 minutes.
assert (
    MIGRATION_TASK_SOFT_TIME_LIMIT_S < MIGRATION_TASK_TIME_LIMIT_S
), "The soft time limit must be less than the time limit."
assert (
    MIGRATION_TASK_TIME_LIMIT_S < MIGRATION_TASK_LOCK_TIMEOUT_S
), "The time limit must be less than the lock timeout."
# Time to wait to acquire the lock.
MIGRATION_TASK_LOCK_BLOCKING_TIMEOUT_S = 60 * 2  # 2 minutes.

# Constants corresponding to check_for_documents_for_opensearch_migration_task.
CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S = 60  # 60 seconds / 1 minute.
CHECK_FOR_DOCUMENTS_TASK_TIME_LIMIT_S = 90  # 90 seconds.
# The maximum time the lock can be held for. Will automatically be released
# after this time.
CHECK_FOR_DOCUMENTS_TASK_LOCK_TIMEOUT_S = 120  # 120 seconds / 2 minutes.
assert (
    CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S < CHECK_FOR_DOCUMENTS_TASK_TIME_LIMIT_S
), "The soft time limit must be less than the time limit."
assert (
    CHECK_FOR_DOCUMENTS_TASK_TIME_LIMIT_S < CHECK_FOR_DOCUMENTS_TASK_LOCK_TIMEOUT_S
), "The time limit must be less than the lock timeout."
# Time to wait to acquire the lock.
CHECK_FOR_DOCUMENTS_TASK_LOCK_BLOCKING_TIMEOUT_S = 30  # 30 seconds.

TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE = 15
