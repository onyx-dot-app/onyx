"""Chat session admission must serialize turns on both shared cache backends."""

from threading import Barrier
from uuid import uuid4

import pytest

from onyx.cache.interface import CacheBackend, CacheLockLostError
from onyx.chat.chat_processing_checker import (
    ChatTurnAdmission,
    get_processing_stream_id,
    is_chat_session_processing,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor


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
        with ContextThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(claim, admissions))
        assert sorted(outcomes) == [False, True]
        old = admissions[outcomes.index(True)]
        old.publish(11)
        assert is_chat_session_processing(session_id, cache)
        # Remove both expired records before another process claims the session.
        cache.delete(f"chatprocessing_fence_{session_id}")
        cache.delete(f"chatprocessing_owner_{session_id}")
        new = ChatTurnAdmission(cache)
        admissions.append(new)
        new.claim(session_id)
        new.publish(12)
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
