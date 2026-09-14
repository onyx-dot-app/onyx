import threading

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def test_cancel_returns_without_waiting_and_does_not_start_queued_tool() -> None:
    signal = CancellationSignal()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    cancelled = threading.Event()
    queued_started = threading.Event()
    errors: list[BaseException] = []

    def blocking_tool() -> None:
        started.set()
        release.wait(5)
        finished.set()

    def execute() -> None:
        try:
            run_functions_tuples_in_parallel(
                [(blocking_tool, ()), (queued_started.set, ())],
                max_workers=1,
                cancellation=signal,
            )
        except AgentCancelled:
            cancelled.set()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    try:
        assert started.wait(2)
        signal.cancel()
        assert cancelled.wait(1), errors
        assert not finished.is_set()
        assert not queued_started.is_set()
    finally:
        release.set()
        worker.join(timeout=3)
    assert finished.wait(1)
    assert not queued_started.is_set()
    assert not errors
