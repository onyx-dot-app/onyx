"""The Celery task allowlist check flags a task or beat entry that is not on
the list, a task outside the task directories or without an OnyxCeleryTask
name, and a list line that is stale, empty or repeated. The shapes come from
this codebase."""

from pathlib import Path

import pytest
from lint import check_celery_task_allowlist

_TASK_DIR_PATH = "onyx/background/celery/tasks/docprocessing/tasks.py"
_EE_TASK_DIR_PATH = "ee/onyx/background/celery/tasks/cleanup/tasks.py"
_SERVER_PATH = "onyx/server/documents/cc_pair.py"
_LABEL = "allowlist.txt"

_SHARED_TASK = """\
@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_INDEX_ATTEMPT_CLEANUP,
    soft_time_limit=300,
    bind=True,
)
def check_for_index_attempt_cleanup(self: Task, *, tenant_id: str) -> None:
    pass
"""

_APP_TASK = """\
@celery_app.task(name=OnyxCeleryTask.CHECK_FOR_INDEXING)
def check_for_indexing(*, tenant_id: str) -> None:
    pass
"""

_BARE_SHARED_TASK = """\
@shared_task
def one_off_fix(*, tenant_id: str) -> None:
    pass
"""

_RAW_NAME_TASK = """\
@shared_task(name="backfill_user_emails", ignore_result=True)
def backfill_user_emails(*, tenant_id: str) -> None:
    pass
"""

_BEAT_TEMPLATE = """\
beat_task_templates.append(
    {
        "name": "backfill-cc-pair-ids",
        "task": OnyxCeleryTask.BACKFILL_CC_PAIR_IDS_TASK,
        "schedule": timedelta(minutes=5),
        "options": {"expires": BEAT_EXPIRES_DEFAULT},
    }
)
"""

_CLOUD_BEAT = """\
beat_cloud_tasks: list[dict] = [
    {
        "name": f"{ONYX_CLOUD_CELERY_TASK_PREFIX}_monitor-alembic",
        "task": OnyxCeleryTask.CLOUD_MONITOR_ALEMBIC,
        "schedule": timedelta(hours=1),
        "options": {"expires": BEAT_EXPIRES_DEFAULT},
    },
]
"""

_MODE_BEAT = """\
_sandbox_reconcile_task: dict[str, Any] = {
    "name": f"{ONYX_CLOUD_CELERY_TASK_PREFIX}_reconcile-sandbox-runtimes"
    if MULTI_TENANT
    else "reconcile-sandbox-runtimes",
    "task": OnyxCeleryTask.RECONCILE_SANDBOX_RUNTIMES,
    "schedule": _sandbox_reconcile_interval,
}
"""

# The scheduler copies each entry with no name; the check leaves it alone.
_SCHEDULER_COPY = """\
for task in tasks_to_schedule:
    tenant_task = {
        "task": task["task"],
        "schedule": task["schedule"],
        "kwargs": {"tenant_id": tenant_id},
    }
"""


def _problems(sources: dict[str, str], allowlist: str) -> list[str]:
    return [
        f"{p.location}: {p.message}"
        for p in check_celery_task_allowlist.check(sources, allowlist, _LABEL)
    ]


def test_listed_task_passes() -> None:
    allowlist = "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: Beat check for old attempts.\n"
    assert _problems({_TASK_DIR_PATH: _SHARED_TASK}, allowlist) == []


def test_new_task_not_on_the_list_is_flagged_with_the_fix() -> None:
    problems = _problems({_TASK_DIR_PATH: _SHARED_TASK}, "")
    assert len(problems) == 1
    assert problems[0].startswith(f"{_TASK_DIR_PATH}:1: task CHECK_FOR_INDEX")
    assert "A run-once backfill or migration is not a task" in problems[0]
    assert "add `task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: <reason>`" in problems[0]


def test_app_task_decorator_counts_as_a_task() -> None:
    problems = _problems({_EE_TASK_DIR_PATH: _APP_TASK}, "")
    assert [p.split(": ", 1)[1][:24] for p in problems] == ["task CHECK_FOR_INDEXING "]


def test_task_outside_the_task_directories_is_flagged() -> None:
    allowlist = "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: Beat check for old attempts.\n"
    problems = _problems({_SERVER_PATH: _SHARED_TASK}, allowlist)
    assert len(problems) == 1
    assert "is outside the task directories" in problems[0]


@pytest.mark.parametrize("source", [_BARE_SHARED_TASK, _RAW_NAME_TASK])
def test_task_without_an_onyx_celery_task_name_is_flagged(source: str) -> None:
    problems = _problems({_TASK_DIR_PATH: source}, "")
    assert len(problems) == 1
    assert "has no OnyxCeleryTask name" in problems[0]


@pytest.mark.parametrize(
    ("source", "names"),
    [
        (_BEAT_TEMPLATE, ["backfill-cc-pair-ids"]),
        (_CLOUD_BEAT, ["{ONYX_CLOUD_CELERY_TASK_PREFIX}_monitor-alembic"]),
        (
            _MODE_BEAT,
            [
                "{ONYX_CLOUD_CELERY_TASK_PREFIX}_reconcile-sandbox-runtimes",
                "reconcile-sandbox-runtimes",
            ],
        ),
    ],
)
def test_beat_entry_names_must_be_on_the_list(source: str, names: list[str]) -> None:
    flagged = _problems({"onyx/background/celery/tasks/beat_schedule.py": source}, "")
    assert [p.split(": ", 1)[1].split(" is not")[0] for p in flagged] == [
        f"beat {name}" for name in names
    ]
    allowlist = "".join(f"beat {name}: A reason.\n" for name in names)
    path = "onyx/background/celery/tasks/beat_schedule.py"
    assert _problems({path: source}, allowlist) == []


def test_beat_entry_with_a_string_task_is_flagged() -> None:
    source = _BEAT_TEMPLATE.replace(
        "OnyxCeleryTask.BACKFILL_CC_PAIR_IDS_TASK", '"backfill_cc_pair_ids_task"'
    )
    problems = _problems(
        {"onyx/background/celery/tasks/beat_schedule.py": source},
        "beat backfill-cc-pair-ids: A reason.\n",
    )
    assert len(problems) == 1
    assert "names its task with a string" in problems[0]


def test_scheduler_copy_without_a_name_is_not_an_entry() -> None:
    assert _problems({"onyx/background/celery/apps/beat.py": _SCHEDULER_COPY}, "") == []


def test_add_periodic_task_is_flagged() -> None:
    source = "app.add_periodic_task(60.0, cleanup.s(), name='cleanup')\n"
    problems = _problems({"onyx/background/celery/apps/primary.py": source}, "")
    assert len(problems) == 1
    assert "add_periodic_task schedules outside the beat schedule" in problems[0]


@pytest.mark.parametrize(
    ("allowlist", "fix"),
    [
        ("task CHECK_FOR_INDEXING: Beat check.\n", "no code defines it"),
        ("task CHECK_FOR_INDEX_ATTEMPT_CLEANUP:\n", "The reason cannot be empty"),
        (
            "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP:  # one-off: remove later\n",
            "The reason cannot be empty",
        ),
        (
            "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: # one-off: remove later\n",
            "The reason cannot be empty",
        ),
        ("CHECK_FOR_INDEX_ATTEMPT_CLEANUP: A reason.\n", "The reason cannot be empty"),
        (
            "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: A reason.\n"
            "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: Again.\n",
            "is on the list twice",
        ),
    ],
)
def test_bad_list_lines_are_flagged(allowlist: str, fix: str) -> None:
    problems = _problems({_TASK_DIR_PATH: _SHARED_TASK}, allowlist)
    assert any(fix in problem for problem in problems), problems


def test_one_off_marker_keeps_the_entry_approved() -> None:
    allowlist = (
        "beat backfill-cc-pair-ids: Resumes the backfill. "
        "# one-off: remove once every deployment finished it\n"
    )
    path = "onyx/background/celery/tasks/beat_schedule.py"
    assert _problems({path: _BEAT_TEMPLATE}, allowlist) == []


def test_comment_and_blank_lines_are_ignored() -> None:
    allowlist = (
        "# Approved tasks.\n\n"
        "task CHECK_FOR_INDEX_ATTEMPT_CLEANUP: Beat check for old attempts.\n"
    )
    assert _problems({_TASK_DIR_PATH: _SHARED_TASK}, allowlist) == []


@pytest.mark.parametrize(
    "source",
    [
        "@celery_app.task\ndef cleanup(*, tenant_id: str) -> None:\n    pass\n",
        "x = {'name': 'cleanup', 'task': OnyxCeleryTask.X, 'schedule': 60}\n",
    ],
)
def test_prefilter_keeps_files_that_define_tasks(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "onyx" / "background" / "celery" / "tasks"
    root.mkdir(parents=True)
    (root / "defines.py").write_text(source)
    (root / "unrelated.py").write_text("x = 1\n")
    monkeypatch.setattr(check_celery_task_allowlist, "_BACKEND_DIR", tmp_path)
    assert list(check_celery_task_allowlist._read_sources()) == [
        "onyx/background/celery/tasks/defines.py"
    ]


def test_backend_tree_matches_the_list() -> None:
    assert check_celery_task_allowlist.main() == 0
