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
    get_processing_stream_id,
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
        old.publish(11)
        old.check_owner(session_id)
        assert is_chat_session_processing(session_id, cache)
        # Remove both expired records before another process claims the session.
        cache.delete(f"chatprocessing_fence_{session_id}")
        cache.delete(f"chatprocessing_owner_{session_id}")
        new = ChatTurnAdmission(cache)
        admissions.append(new)
        new.claim(session_id)
        new.publish(12)
        new.check_owner(session_id)
        with pytest.raises(CacheLockLostError):
            old.check_owner(session_id)
        with pytest.raises(CacheLockLostError):
            old.publish(11)
        with pytest.raises(CacheLockLostError):
            old.refresh()
        old.release()
        assert get_processing_stream_id(session_id, cache) == 12
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
        second.publish(21)
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
