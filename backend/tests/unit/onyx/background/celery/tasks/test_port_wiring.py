"""Guards the Celery wiring of the reindex-port flow.

The port logic itself is covered by the external_dependency_unit `db/test_*port*`
suites (which run against real Postgres/OpenSearch). Those mock the celery app, so
nothing there proves a beat-enqueued port task actually reaches a worker. These
unit tests guard exactly that transport seam — the part a dropped autodiscover line
or `-Q` entry would silently break with every other test still green:

  beat schedules check_for_port  ->  docprocessing worker consumes the `port` queue
  ->  docprocessing worker has run_port_attempt registered to execute it.
"""

import re
from pathlib import Path

from onyx.background.celery.tasks.beat_schedule import beat_task_templates
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask


def _find_supervisord_conf() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "supervisord.conf"
        if candidate.is_file():
            return candidate
    raise AssertionError("supervisord.conf not found above this test")


def _worker_queues(program: str) -> set[str]:
    """The `-Q` queue set a supervisord worker program consumes.

    Reads the queues from anywhere in the `[program:*]` block, so it survives the
    `command=celery ... -Q a,b,c` being on one line or wrapped across several.
    """
    conf = _find_supervisord_conf().read_text()
    block = re.search(
        rf"^\[program:{re.escape(program)}\]\n(.*?)(?=^\[|\Z)",
        conf,
        re.DOTALL | re.MULTILINE,
    )
    if block is None:
        raise AssertionError(f"no [program:{program}] block found")
    queues = re.search(r"-Q\s+(\S+)", block.group(1))
    if queues is None:
        raise AssertionError(f"no -Q queues found in [program:{program}]")
    return set(queues.group(1).split(","))


def test_check_for_port_scheduled_in_beat() -> None:
    # check_for_port is the only producer of PortAttempts; if it falls out of the
    # beat schedule the whole flow stops with zero other test failures.
    scheduled = {t["task"] for t in beat_task_templates}
    if DISABLE_VECTOR_DB:
        # Vector-DB-gated: must be filtered out of minimal-mode deployments.
        assert OnyxCeleryTask.CHECK_FOR_PORT not in scheduled
    else:
        assert OnyxCeleryTask.CHECK_FOR_PORT in scheduled


def test_docprocessing_worker_consumes_port_queue() -> None:
    # run_port_attempt is enqueued to the PORT queue; the docprocessing worker is its
    # only consumer. Dropping `port` from this `-Q` list strands every port task.
    assert OnyxCeleryQueues.PORT in _worker_queues("celery_worker_docprocessing")


def test_docprocessing_worker_registers_port_tasks() -> None:
    # Consuming the queue is moot if autodiscovery doesn't register the task body:
    # the worker would reject it as unknown. Importing + loading the docprocessing app
    # mirrors worker bootstrap, so run_port_attempt must resolve by name.
    from onyx.background.celery.apps.docprocessing import celery_app

    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())
    assert OnyxCeleryTask.RUN_PORT_ATTEMPT in registered
