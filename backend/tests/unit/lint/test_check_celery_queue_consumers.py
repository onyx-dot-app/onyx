"""The queue check finds queues named in send calls and beat options,
resolves `OnyxCeleryQueues` constants, honours an allow marker only with a
reason, and reads worker `-Q` lists from supervisord and Helm."""

from lint import check_celery_queue_consumers as check

_CONSTANTS = {"PRIMARY": "celery", "HEAVY": "connector_pruning"}


def test_send_calls_and_beat_options_name_their_queues() -> None:
    source = (
        "app.send_task(T, queue=OnyxCeleryQueues.HEAVY, expires=1)\n"
        't.apply_async(queue="raw_queue")\n'
        'ENTRY = {"task": T, "options": {"queue": OnyxCeleryQueues.PRIMARY}}\n'
    )
    assert check.find_used_queues(source, _CONSTANTS) == [
        (1, "connector_pruning"),
        (2, "raw_queue"),
        (3, "celery"),
    ]


def test_calls_without_a_resolvable_queue_are_skipped() -> None:
    source = (
        "app.send_task(T, expires=1)\n"
        "app.send_task(T, queue=queue_for(x))\n"
        "app.send_task(T, queue=OnyxCeleryQueues.UNKNOWN)\n"
        "other.call(queue=OnyxCeleryQueues.HEAVY)\n"
    )
    assert check.find_used_queues(source, _CONSTANTS) == []


def test_allow_marker_exempts_and_needs_a_reason() -> None:
    allowed = "app.send_task(T, queue='q')  # celery-queue: allow optional worker\n"
    bare = "app.send_task(T, queue='q')  # celery-queue: allow\n"
    assert check.find_used_queues(allowed, _CONSTANTS) == []
    assert check.bad_markers(allowed) == []
    assert check.bad_markers(bare) == [1]


def test_queue_constants_reads_the_class() -> None:
    source = 'class OnyxCeleryQueues:\n    PRIMARY = "celery"\n    HEAVY = "h"\n'
    assert check.queue_constants(source) == {"PRIMARY": "celery", "HEAVY": "h"}


def test_consumed_queues_from_supervisord_and_helm() -> None:
    supervisord = "command=celery worker\n    -Q a,b\nx -Q c;; esac'\n"
    helm = '              "-Q",\n              "d,e",\n'
    assert check.consumed_queues(supervisord, check._SUPERVISORD_QUEUES) == {
        "a",
        "b",
        "c",
    }
    assert check.consumed_queues(helm, check._HELM_QUEUES) == {"d", "e"}
