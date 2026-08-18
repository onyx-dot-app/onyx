"""Unit tests for the supervisor-managed process matching logic used by
monitor_process_memory.
"""

from onyx.background.celery.tasks.monitoring.tasks import (
    _match_supervisor_processes,
)

# Real command lines, taken directly from the `[program:...]` entries in
# backend/supervisord.conf, with process-manager-added suffixes (e.g.
# `@%n` hostname expansion) approximated with a literal host id.
PRIMARY_CMDLINE = (
    "celery -A onyx.background.celery.versioned_apps.primary worker "
    "--hostname=primary@host -Q celery"
)
DOCPROCESSING_CMDLINE = (
    "celery -A onyx.background.celery.versioned_apps.docprocessing worker "
    "--hostname=docprocessing@host -Q docprocessing,port"
)
BEAT_CMDLINE = "celery -A onyx.background.celery.versioned_apps.beat beat"
BEAT_WATCHDOG_CMDLINE = (
    "python -m onyx.utils.supervisord_watchdog "
    "--conf /etc/supervisor/conf.d/supervisord.conf "
    '--key "onyx:celery:beat:heartbeat" --program celery_beat'
)
LOG_REDIRECT_CMDLINE = (
    "tail -qF /var/log/celery_beat.log /var/log/celery_worker_primary.log "
    "/var/log/supervisord_watchdog_celery_beat.log"
)
SLACK_CMDLINE = "python onyx/onyxbot/slack/listener.py"

CURRENT_PROCESS_TYPE_MAPPING = {
    "--hostname=primary": "primary",
    "--hostname=light": "light",
    "--hostname=heavy": "heavy",
    "--hostname=docprocessing": "docprocessing",
    "--hostname=user_file_processing": "user_file_processing",
    "--hostname=scheduled_tasks": "scheduled_tasks",
    "--hostname=docfetching": "docfetching",
    "--hostname=monitoring": "monitoring",
    "versioned_apps.beat beat": "beat",
    "slack/listener.py": "slack",
}


def test_matches_each_process_exactly_once() -> None:
    process_cmdlines = {
        1: PRIMARY_CMDLINE,
        2: DOCPROCESSING_CMDLINE,
        3: BEAT_CMDLINE,
        4: SLACK_CMDLINE,
    }

    supervisor_processes, duplicate_warnings = _match_supervisor_processes(
        process_cmdlines, CURRENT_PROCESS_TYPE_MAPPING
    )

    assert supervisor_processes == {
        1: "primary",
        2: "docprocessing",
        3: "beat",
        4: "slack",
    }
    assert duplicate_warnings == []


def test_beat_watchdog_and_log_redirect_do_not_false_match_as_beat() -> None:
    # Regression test: previously, the bare "beat" substring also matched
    # the beat watchdog (cmdline references "celery_beat") and the
    # log-redirect-handler (cmdline references celery_beat.log), which were
    # then logged as duplicate "beat" processes even though only one real
    # celery beat process was running.
    process_cmdlines = {
        1: BEAT_CMDLINE,
        2: BEAT_WATCHDOG_CMDLINE,
        3: LOG_REDIRECT_CMDLINE,
    }

    supervisor_processes, duplicate_warnings = _match_supervisor_processes(
        process_cmdlines, CURRENT_PROCESS_TYPE_MAPPING
    )

    assert supervisor_processes == {1: "beat"}
    assert duplicate_warnings == []


def test_genuine_duplicate_is_still_reported() -> None:
    # If the same process type is somehow started twice, that's still a
    # real condition worth flagging.
    process_cmdlines = {
        1: PRIMARY_CMDLINE,
        2: PRIMARY_CMDLINE,
    }

    supervisor_processes, duplicate_warnings = _match_supervisor_processes(
        process_cmdlines, CURRENT_PROCESS_TYPE_MAPPING
    )

    assert supervisor_processes == {1: "primary"}
    assert len(duplicate_warnings) == 1
    assert "Duplicate process type for type primary" in duplicate_warnings[0]
