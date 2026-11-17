"""Chat session admission must serialize turns on both shared cache backends."""

import contextvars
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest

from onyx.cache.interface import CacheBackend, CacheLockLostError
from onyx.chat.chat_processing_checker import (
    ChatTurnAdmission,
    current_turn_owner,
    get_processing_stream,
    is_chat_session_processing,
    stop_current_turn,
)
from onyx.chat.stop_signal_checker import is_stop_requested
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def test_concurrent_claim_and_stale_owner_cleanup(cache: CacheBackend) -> None:
    session_id = uuid4()
    admissions = [ChatTurnAdmission(cache), ChatTurnAdmission(cache)]
    barrier = Barrier(2)

    def claim(admission: ChatTurnAdmission) -> bool:
        barrier.wait(timeout=5)
        try:
            admission.claim(session_id)
            return True
        except OnyxError as error:
            assert error.error_code is OnyxErrorCode.CONFLICT
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            tasks = [
                workers.submit(contextvars.copy_context().run, claim, admission)
                for admission in admissions
            ]
            outcomes = [cast(bool, task.result()) for task in tasks]
        assert sorted(outcomes) == [False, True]
        old = admissions[outcomes.index(True)]
        old.publish(11, [])
        old.check_owner(session_id)
        assert is_chat_session_processing(session_id, cache)
        # Remove both expired records before another process claims the session.
        cache.delete(f"chatprocessing_fence_{session_id}")
        cache.delete(f"chatprocessing_owner_{session_id}")
        new = ChatTurnAdmission(cache)
        admissions.append(new)
        new.claim(session_id)
        new.publish(12, [])
        new.check_owner(session_id)
        with pytest.raises(CacheLockLostError):
            old.check_owner(session_id)
        with pytest.raises(CacheLockLostError):
            old.publish(11, [])
        with pytest.raises(CacheLockLostError):
            old.refresh()
        old.release()
        assert get_processing_stream(session_id, cache) == (12, [], False)
        new.refresh()
        new.release()
        assert not is_chat_session_processing(session_id, cache)
    finally:
        for admission in admissions:
            admission.release()


def test_stop_targets_the_turn_that_holds_admission(cache: CacheBackend) -> None:
    session_id = uuid4()
    first, second = ChatTurnAdmission(cache), ChatTurnAdmission(cache)
    preparation_stop = f"chatprocessing_preparation_stop_{session_id}"
    pauses: list[None] = []
    try:
        stop_current_turn(session_id, cache, pause_queue=lambda: pauses.append(None))
        assert pauses == [None]
        first.claim(session_id)
        finished = current_turn_owner(session_id, cache)
        assert finished is not None
        # A Stop pauses the queue whether or not a turn holds admission.
        stop_current_turn(session_id, cache, pause_queue=lambda: pauses.append(None))
        assert pauses == [None, None]
        # The preparation Stop lasts as long as the admission it targets.
        cache.expire(preparation_stop, 5)
        first.refresh()
        assert cache.ttl(preparation_stop) > 5
        first.release()
        second.claim(session_id)
        second.publish(21, [])
        assert not is_stop_requested(session_id, cache, stream_id=21)
        # A Stop aimed at the finished turn does not reach the next one.
        stop_current_turn(session_id, cache, owner=finished)
        assert not is_stop_requested(session_id, cache, stream_id=21)
        stop_current_turn(session_id, cache)
        assert is_stop_requested(session_id, cache, stream_id=21)
    finally:
        first.release()
        second.release()
        cache.delete(preparation_stop)
        cache.delete(f"chatsessionstop_fence_{session_id}_21")


def test_the_fence_keeps_the_stream_id_that_every_server_version_reads(
    cache: CacheBackend,
) -> None:
    """During a rolling deploy, older servers read the fence as a bare stream
    ID; the responses of the stream are kept beside it."""
    session_id = uuid4()
    fence = f"chatprocessing_fence_{session_id}"
    turn = ChatTurnAdmission(cache)
    try:
        turn.claim(session_id)
        turn.publish(31, [5, 6], resumed=True)
        raw = cache.get(fence)
        assert raw is not None and int(raw.decode("utf-8")) == 31
        assert get_processing_stream(session_id, cache) == (31, [5, 6], True)
        turn.release()
        assert get_processing_stream(session_id, cache) is None
        # An older server's turn publishes no responses.
        turn.claim(session_id)
        cache.set(fence, 32, ex=60)
        assert get_processing_stream(session_id, cache) == (32, [], False)
    finally:
        turn.release()


def test_a_turn_hands_admission_to_the_next_turn_without_an_idle_gap(
    cache: CacheBackend,
) -> None:
    """A turn that ends with work to continue keeps the chat processing and
    hands admission to the next turn's preparation; a Stop aimed at the
    ending turn does not reach the next one."""
    session_id = uuid4()
    ending = ChatTurnAdmission(cache)
    successor: ChatTurnAdmission | None = None
    try:
        ending.claim(session_id)
        ending.publish(41, [7], resumed=False)
        finished = current_turn_owner(session_id, cache)

        successor = ending.release(hand_off=lambda: True)

        assert successor is not None
        assert is_chat_session_processing(session_id, cache)
        assert get_processing_stream(session_id, cache) is None
        assert current_turn_owner(session_id, cache) not in (None, finished)
        stop_current_turn(session_id, cache, owner=finished)
        assert not cache.exists(f"chatprocessing_preparation_stop_{session_id}")
        successor.check_owner(session_id)
        successor.publish(42, [7], resumed=True)
        assert get_processing_stream(session_id, cache) == (42, [7], True)
        assert successor.release(hand_off=lambda: False) is None
        assert not is_chat_session_processing(session_id, cache)
    finally:
        ending.release()
        if successor is not None:
            successor.release()
