"""The Celery expiry check flags a send, a delay() and a beat schedule entry
with no expiry, leaves the shapes that carry one alone, and accepts an allow
marker only when it gives a reason. The shapes come from this codebase."""

from pathlib import Path

import pytest
from lint import check_celery_task_expires

_SEND_WITHOUT_EXPIRES = """\
client_app.send_task(
    OnyxCeleryTask.CHECK_FOR_INDEXING,
    kwargs={"tenant_id": tenant_id},
    priority=OnyxCeleryPriority.HIGH,
)
"""

_SEND_WITH_EXPIRES = """\
client_app.send_task(
    OnyxCeleryTask.CHECK_FOR_INDEXING,
    kwargs={"tenant_id": tenant_id},
    priority=OnyxCeleryPriority.HIGH,
    expires=CHECK_FOR_INDEXING_EXPIRES_SECONDS,
)
"""

_SEND_ASSIGNED_IN_TASK = """\
def try_creating_prune_generator_task() -> None:
    result = celery_app.send_task(
        OnyxCeleryTask.CONNECTOR_PRUNING_GENERATOR_TASK,
        kwargs={"cc_pair_id": cc_pair.id, "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.CONNECTOR_PRUNING,
        task_id=custom_task_id,
        priority=OnyxCeleryPriority.LOW,
        headers={"enqueued_at": time.time()},
    )
"""

_SEND_WITH_SPREAD_AND_EXPIRES = """\
self.app.send_task(
    OnyxCeleryTask.RUN_SCHEDULED_TASK,
    kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
    queue=OnyxCeleryQueues.SCHEDULED_TASKS,
    expires=RUN_EXPIRES_SECONDS,
    headers={"enqueued_at": time.time()},
    **extra_options,
)
"""

_BEAT_ENTRY = """\
beat_task_templates: list[dict] = [
    {{
        "name": "check-for-indexing",
        "task": OnyxCeleryTask.CHECK_FOR_INDEXING,
        "schedule": timedelta(seconds=15),
        {options}
    }},
]
"""

_BEAT_OPTIONS_WITH_EXPIRES = """\
"options": {
            "priority": OnyxCeleryPriority.MEDIUM,
            "expires": BEAT_EXPIRES_DEFAULT,
        },"""

_BEAT_OPTIONS_WITHOUT_EXPIRES = """\
"options": {"priority": OnyxCeleryPriority.MEDIUM},"""

# The scheduler copies an entry and attaches its options in a later statement.
_BEAT_FORWARDER = """\
for task in tasks_to_schedule:
    tenant_task = {{{marker}
        "task": task["task"],
        "schedule": task["schedule"],
        "kwargs": {{"tenant_id": tenant_id}},
    }}
    if options := task.get("options"):
        tenant_task["options"] = options
"""


@pytest.mark.parametrize(
    ("source", "line", "fix"),
    [
        (_SEND_WITHOUT_EXPIRES, 1, "send_task() has no expires="),
        (_SEND_ASSIGNED_IN_TASK, 2, "send_task() has no expires="),
        (
            "task.apply_async(kwargs={'tenant_id': tenant_id}, queue=queue)\n",
            1,
            "apply_async() has no expires=",
        ),
        (
            "app.send_task(name, kwargs=kwargs, **options)\n",
            1,
            "send_task() has no expires=",
        ),
        (
            "app.send_task(name, kwargs=kwargs, expires=None)\n",
            1,
            "send_task() has expires=None",
        ),
        (
            "cleanup_checkpoint_task.delay(index_attempt_id=1, tenant_id=tenant_id)\n",
            1,
            "delay() cannot set an expiry",
        ),
        (
            _BEAT_ENTRY.format(options=_BEAT_OPTIONS_WITHOUT_EXPIRES),
            2,
            'beat schedule entry has no "expires"',
        ),
        (
            _BEAT_ENTRY.format(options='"options": {"expires": None},'),
            2,
            'beat schedule entry has no "expires"',
        ),
        (_BEAT_ENTRY.format(options=""), 2, 'beat schedule entry has no "expires"'),
        (
            _BEAT_ENTRY.format(options='"options": shared_options,'),
            2,
            'beat schedule entry has no "expires"',
        ),
        (
            _BEAT_FORWARDER.format(marker=""),
            2,
            'beat schedule entry has no "expires"',
        ),
    ],
)
def test_enqueue_without_expiry_is_flagged(source: str, line: int, fix: str) -> None:
    found = check_celery_task_expires.find_missing_expires(source)
    assert list(found) == [line]
    assert fix in found[line]


@pytest.mark.parametrize(
    "source",
    [
        _SEND_WITH_EXPIRES,
        _SEND_WITH_SPREAD_AND_EXPIRES,
        "task.apply_async(kwargs={'tenant_id': tenant_id}, expires=expires)\n",
        _BEAT_ENTRY.format(options=_BEAT_OPTIONS_WITH_EXPIRES),
        # Not an enqueue: a local task run in tests, a retry, a revoke.
        "connector_pruning_generator_task.apply(kwargs={'cc_pair_id': 1})\n",
        "self.retry(exc=e, countdown=countdown)\n",
        "client_app.control.revoke(task_id)\n",
        # A dict that is not a schedule entry.
        '{"task": OnyxCeleryTask.CHECK_FOR_INDEXING, "name": "check"}\n',
        # asyncio code names a variable send_task; only a method call counts.
        "send_task = asyncio.create_task(send_audio())\n",
    ],
)
def test_enqueue_with_expiry_and_other_shapes_pass(source: str) -> None:
    assert check_celery_task_expires.find_missing_expires(source) == {}


@pytest.mark.parametrize(
    "source",
    [
        _SEND_WITHOUT_EXPIRES.replace(
            "send_task(", "send_task(  # celery-expires: allow (may wait hours)"
        ),
        _SEND_ASSIGNED_IN_TASK.replace(
            "send_task(", "send_task(  # celery-expires: allow (may wait hours)"
        ),
        _BEAT_FORWARDER.format(marker="  # celery-expires: allow (copies an entry)"),
    ],
)
def test_allow_marker_with_reason_exempts_the_statement(source: str) -> None:
    assert check_celery_task_expires.find_missing_expires(source) == {}


@pytest.mark.parametrize(
    "marker", ["# celery-expires: allow", "# celery-expires: allow ()"]
)
def test_allow_marker_without_reason_is_flagged(marker: str) -> None:
    source = _SEND_WITHOUT_EXPIRES.replace("send_task(", f"send_task(  {marker}")
    found = check_celery_task_expires.find_missing_expires(source)
    assert list(found) == [1]
    assert "needs a reason" in found[1]


def test_allow_marker_in_a_string_does_not_exempt() -> None:
    source = 'app.send_task("celery-expires: allow (not a comment)")\n'
    assert list(check_celery_task_expires.find_missing_expires(source)) == [1]


def test_allow_marker_exempts_one_statement_only() -> None:
    source = (
        "app.send_task(name)  # celery-expires: allow (may wait hours)\n"
        "app.send_task(other)\n"
    )
    assert list(check_celery_task_expires.find_missing_expires(source)) == [2]


def test_main_names_file_line_and_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(_SEND_WITHOUT_EXPIRES)
    good = tmp_path / "good.py"
    good.write_text(_SEND_WITH_EXPIRES)

    assert check_celery_task_expires.main([str(good)]) == 0
    assert check_celery_task_expires.main([str(bad), str(good)]) == 1
    output = capsys.readouterr().out
    assert f"{bad}:1: send_task() has no expires=. Add expires=<seconds>" in output
    assert str(good) not in output
    assert "celery-expires: allow (<reason>)" in output


def test_backend_tree_has_no_enqueue_without_expiry() -> None:
    assert check_celery_task_expires.main([]) == 0
