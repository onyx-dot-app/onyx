import threading
import time

from onyx.utils.timing import PausableClock


def test_the_clock_stands_still_while_paused() -> None:
    clock = PausableClock()
    clock.set_paused(True)
    paused_at = clock.now()
    time.sleep(0.2)
    # A second pause request does not restart the pause.
    clock.set_paused(True)

    assert clock.now() - paused_at < 0.1
    assert clock.paused_seconds >= 0.2

    clock.set_paused(False)
    paused_seconds = clock.paused_seconds
    time.sleep(0.1)

    assert clock.now() - paused_at >= 0.1
    assert clock.paused_seconds == paused_seconds


def test_a_wait_on_a_deadline_ends_after_the_active_time() -> None:
    """A waiter that times out during a pause waits again for what is left."""
    clock = PausableClock()
    deadline = clock.now() + 0.3
    resumed = threading.Timer(0.2, clock.set_paused, args=(False,))
    clock.set_paused(True)
    started = time.monotonic()
    resumed.start()

    while (remaining := deadline - clock.now()) > 0:
        time.sleep(remaining)

    assert time.monotonic() - started >= 0.5
    resumed.join()
