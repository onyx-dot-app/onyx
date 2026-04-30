"""External dependency tests for redis_shared_lock context manager.

These tests require Redis to be running.
"""

import threading
import time
from collections.abc import Generator

import pytest

from onyx.redis.lock_context import redis_shared_lock
from onyx.redis.lock_context import RedisSharedLockAcquisitionError
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

TEST_LOCK_NAME = "test_shared_lock"
TEST_LOCK_NAME_OTHER = "test_shared_lock_other"


@pytest.fixture(autouse=True)
def _clean_locks() -> Generator[None, None, None]:
    """
    Ensures the test lock keys are cleared before and after each test so runs
    never collide with leftovers from prior failures.
    """
    redis_client = get_shared_redis_client()
    redis_client.delete(TEST_LOCK_NAME, TEST_LOCK_NAME_OTHER)
    yield
    redis_client.delete(TEST_LOCK_NAME, TEST_LOCK_NAME_OTHER)


def test_acquire_and_release() -> None:
    """
    Tests that a single caller can acquire the lock, gets a token, and releases
    on exit.
    """
    # Precondition.
    redis_client = get_shared_redis_client()
    assert not redis_client.exists(
        TEST_LOCK_NAME
    ), "Lock key should not exist before the test."

    # Under test.
    with redis_shared_lock(
        lock_name=TEST_LOCK_NAME,
        max_time_lock_held_s=30.0,
        wait_for_lock_s=1.0,
        logger=logger,
    ) as token:
        assert isinstance(token, (str, bytes)), "Token is not a string or bytes."
        assert token, "Token is empty."
        # While inside the context, the lock key exists in redis.
        assert redis_client.exists(
            TEST_LOCK_NAME
        ), "Lock key should exist inside the context."

    # Postcondition.
    assert not redis_client.exists(
        TEST_LOCK_NAME
    ), "Lock key should not exist after exiting the context."


def test_second_acquirer_times_out_while_first_holds() -> None:
    """
    Tests that a second thread cannot acquire the lock while a first still holds
    it.
    """
    # Precondition.
    first_holding = threading.Event()
    first_release = threading.Event()

    def first_holder() -> None:
        with redis_shared_lock(
            lock_name=TEST_LOCK_NAME,
            max_time_lock_held_s=30.0,
            wait_for_lock_s=1.0,
            logger=logger,
        ):
            first_holding.set()
            # Hold the lock until the main thread says we can release.
            first_release.wait(timeout=10.0)

    holder_thread = threading.Thread(target=first_holder)
    holder_thread.start()
    try:
        assert first_holding.wait(
            timeout=5.0
        ), "First holder thread never acquired the lock."

        blocking_timeout = 0.5

        # Under test.
        start = time.monotonic()
        with pytest.raises(RedisSharedLockAcquisitionError):
            with redis_shared_lock(
                lock_name=TEST_LOCK_NAME,
                max_time_lock_held_s=30.0,
                wait_for_lock_s=blocking_timeout,
                logger=logger,
            ):
                pytest.fail("Second thread acquire should not have succeeded.")

        # Postcondition.
        elapsed = time.monotonic() - start
        # We should have waited roughly the blocking timeout before failing.
        assert (
            blocking_timeout / 2 < elapsed < blocking_timeout * 2
        ), f"Unexpected wait duration: {elapsed:.3f} seconds."
    finally:
        first_release.set()
        holder_thread.join(timeout=5.0)
        assert (
            not holder_thread.is_alive()
        ), "First holder thread should not be alive after joining."


def test_second_acquirer_gets_lock_after_first_releases() -> None:
    """
    Tests that once the first holder releases, a waiting second thread should
    succeed in acquiring the lock.
    """
    # Precondition.
    first_holding = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_acquired = threading.Event()
    errors: list[BaseException] = []

    def first_holder() -> None:
        try:
            with redis_shared_lock(
                lock_name=TEST_LOCK_NAME,
                max_time_lock_held_s=30.0,
                wait_for_lock_s=1.0,
                logger=logger,
            ):
                first_holding.set()
                # Hold the lock until the main thread signals release.
                first_release.wait(timeout=10.0)
        except BaseException as e:
            errors.append(e)

    def second_waiter() -> None:
        try:
            second_started.set()
            with redis_shared_lock(
                lock_name=TEST_LOCK_NAME,
                max_time_lock_held_s=30.0,
                wait_for_lock_s=5.0,
                logger=logger,
            ):
                second_acquired.set()
        except BaseException as e:
            errors.append(e)

    holder_thread = threading.Thread(target=first_holder)
    holder_thread.start()
    assert first_holding.wait(
        timeout=5.0
    ), "First holder thread never acquired the lock."

    waiter_thread = threading.Thread(target=second_waiter)
    waiter_thread.start()

    assert second_started.wait(timeout=5.0), "Second waiter thread never started."
    # Waiter cannot succeed while the holder is still inside the context.
    assert (
        not second_acquired.is_set()
    ), "Second waiter thread acquired the lock before the first thread released it."

    # Under test.
    # Release the holder thread.
    first_release.set()

    holder_thread.join(timeout=10.0)
    waiter_thread.join(timeout=10.0)

    # Postcondition.
    assert (
        not holder_thread.is_alive()
    ), "Holder thread should not be alive after joining."
    assert (
        not waiter_thread.is_alive()
    ), "Waiter thread should not be alive after joining."
    assert not errors, f"Thread errors: {errors}"
    assert second_acquired.is_set(), "Second waiter never acquired the lock."


def test_lock_auto_releases_after_max_time() -> None:
    """
    Tests that if a holder overruns max_time_lock_held_s, redis should expire
    the lock.
    """
    first_acquired = threading.Event()
    first_done = threading.Event()
    second_acquired = threading.Event()
    errors: list[BaseException] = []

    # Very short auto-release time.
    max_time_lock_held_s = 0.1

    def overrunning_holder() -> None:
        try:
            with redis_shared_lock(
                lock_name=TEST_LOCK_NAME,
                max_time_lock_held_s=max_time_lock_held_s,
                wait_for_lock_s=1.0,
                logger=logger,
            ):
                first_acquired.set()
                # Sleep much longer than max_time_lock_held_s. Redis should
                # release the lock while we are still "inside".
                time.sleep(max_time_lock_held_s * 10)
        except BaseException as e:
            errors.append(e)
        finally:
            first_done.set()

    def second_acquirer() -> None:
        try:
            # Wait longer than max_time_lock_held_s so we definitely get in.
            # Wait less than the time overrunning_holder sleeps to ensure we get
            # in due to autoexpiry.
            with redis_shared_lock(
                lock_name=TEST_LOCK_NAME,
                max_time_lock_held_s=30.0,
                wait_for_lock_s=max_time_lock_held_s * 5,
                logger=logger,
            ):
                second_acquired.set()
        except BaseException as e:
            errors.append(e)

    holder_thread = threading.Thread(target=overrunning_holder)
    holder_thread.start()
    assert first_acquired.wait(
        timeout=5.0
    ), "First holder thread never acquired the lock."

    # Under test.
    waiter_thread = threading.Thread(target=second_acquirer)
    waiter_thread.start()

    holder_thread.join(timeout=10.0)
    waiter_thread.join(timeout=10.0)

    # Postcondition.
    assert (
        not holder_thread.is_alive()
    ), "Holder thread should not be alive after joining."
    assert (
        not waiter_thread.is_alive()
    ), "Waiter thread should not be alive after joining."
    assert not errors, f"Thread errors: {errors}"
    assert first_done.is_set(), "First holder thread should have finished."
    assert second_acquired.is_set(), "Second acquirer thread never got the lock."


def test_different_lock_names_do_not_block_each_other() -> None:
    """Tests that locks with different names do not block each other."""
    with redis_shared_lock(
        lock_name=TEST_LOCK_NAME,
        max_time_lock_held_s=30.0,
        wait_for_lock_s=1.0,
        logger=logger,
    ):
        # A different lock name should be freely acquirable while the first lock
        # is still held.
        with redis_shared_lock(
            lock_name=TEST_LOCK_NAME_OTHER,
            max_time_lock_held_s=30.0,
            wait_for_lock_s=1.0,
            logger=logger,
        ):
            pass


def test_lock_released_when_body_raises() -> None:
    """
    Tests that exceptions raised inside the context must still release the lock.
    """
    with pytest.raises(RuntimeError):
        with redis_shared_lock(
            lock_name=TEST_LOCK_NAME,
            max_time_lock_held_s=30.0,
            wait_for_lock_s=1.0,
            logger=logger,
        ):
            raise RuntimeError("Boom")

    redis_client = get_shared_redis_client()
    assert not redis_client.exists(
        TEST_LOCK_NAME
    ), "Lock key should not exist after the exception was raised."

    # And a subsequent acquisition should succeed immediately.
    with redis_shared_lock(
        lock_name=TEST_LOCK_NAME,
        max_time_lock_held_s=30.0,
        wait_for_lock_s=1.0,
        logger=logger,
    ):
        pass
