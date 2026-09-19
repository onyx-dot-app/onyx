"""Guards which stale incognito uploads the sweep queues for deletion.

Two shapes with different fates: an upload no session ever claimed goes without
asking anything, and one a session holds goes only once that session's live
context is gone. A session that is still live has its orphan clock restarted so
it cannot occupy every pass.
"""

from collections.abc import Collection
from unittest.mock import patch
from uuid import UUID, uuid4

from onyx.chat.incognito import sweep_stale_incognito_user_files

MODULE = "onyx.chat.incognito"


def _sweep(
    unadopted: list[UUID], sessions: list[UUID], ended: set[UUID]
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    """Returns what the sweep marked, which sessions it asked about, and which
    it touched, having checked it marked exactly what it returned."""
    asked: list[UUID] = []

    def _ended(session_ids: Collection[UUID]) -> set[UUID]:
        asked.extend(session_ids)
        return {session_id for session_id in session_ids if session_id in ended}

    with (
        patch(f"{MODULE}.stale_unadopted_upload_ids", return_value=list(unadopted)),
        patch(f"{MODULE}.stale_incognito_session_ids", return_value=sessions),
        patch(f"{MODULE}.incognito_sessions_ended", side_effect=_ended),
        patch(
            f"{MODULE}.stale_upload_ids_for_sessions",
            side_effect=lambda _db, ids: [UUID(int=i) for i, _ in enumerate(ids, 1)],
        ),
        patch(f"{MODULE}.touch_incognito_uploads_for_sessions") as touch,
        patch(f"{MODULE}.mark_user_files_deleting") as mark,
    ):
        queued = sweep_stale_incognito_user_files(db_session=None)  # ty: ignore[invalid-argument-type]
        assert [call.args[1] for call in mark.call_args_list] == [queued]
        touched = list(touch.call_args.args[1]) if touch.call_args else []
    return queued, asked, touched


def test_an_unadopted_upload_goes_without_a_liveness_check() -> None:
    file_id = uuid4()

    queued, asked, _ = _sweep(unadopted=[file_id], sessions=[], ended=set())

    assert queued == [file_id]
    assert asked == []


def test_a_live_session_keeps_its_uploads_and_leaves_the_window() -> None:
    live = uuid4()

    queued, asked, touched = _sweep(unadopted=[], sessions=[live], ended=set())

    assert queued == []
    assert asked == [live]
    # Its clock restarts, so it cannot occupy the next pass as well.
    assert touched == [live]


def test_a_dead_session_has_its_uploads_queued_alongside_the_unadopted() -> None:
    orphan, live, dead = uuid4(), uuid4(), uuid4()

    queued, asked, touched = _sweep(
        unadopted=[orphan], sessions=[live, dead], ended={dead}
    )

    assert queued[0] == orphan
    assert len(queued) == 2
    assert sorted(asked) == sorted([live, dead])
    assert touched == [live]
