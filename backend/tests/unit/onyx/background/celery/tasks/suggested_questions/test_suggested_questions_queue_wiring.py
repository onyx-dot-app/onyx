"""Guards the transport seam of suggested-question runs: the request side sends
to the suggested_questions queue, and nothing else proves a worker consumes it.
Dropping the queue from a worker's queue list would strand every run with all
other tests still green."""

import re
from pathlib import Path

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask


def _find_above(name: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / name
        if candidate.exists():
            return candidate
    raise AssertionError(f"{name} not found above this test")


def _supervisord_queues(program: str) -> set[str]:
    conf = _find_above("supervisord.conf").read_text()
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


def test_the_light_worker_consumes_the_queue() -> None:
    assert OnyxCeleryQueues.SUGGESTED_QUESTIONS in _supervisord_queues(
        "celery_worker_light"
    )


def test_the_helm_light_worker_consumes_the_queue() -> None:
    template = (
        _find_above("deployment")
        / "helm/charts/onyx/templates/celery-worker-light.yaml"
    ).read_text()
    queues = re.search(r'"(vespa_metadata_sync,[^"]+)"', template)

    assert queues is not None
    assert OnyxCeleryQueues.SUGGESTED_QUESTIONS in queues.group(1).split(",")


def test_the_light_worker_registers_both_tasks() -> None:
    # Consuming the queue is moot if autodiscovery does not register the tasks:
    # the worker would reject them as unknown.
    from onyx.background.celery.apps.light import celery_app

    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())
    tasks = {
        OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_POOL,
        OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_FOR_USER,
    }
    if DISABLE_VECTOR_DB:
        # The runs search the index, so they are left out without one.
        assert not tasks & registered
    else:
        assert tasks <= registered
