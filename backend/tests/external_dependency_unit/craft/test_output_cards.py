"""Persist turn output cards and viewed revisions against PostgreSQL."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.models import Artifact, BuildSession, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.artifact import mark_outputs_viewed
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    OutputsManifestEntry,
    OutputsManifestResponse,
)
from onyx.server.features.build.session.api import (
    get_output_cards,
    view_output_card,
    view_output_cards,
)
from onyx.server.features.build.session.models import (
    OutputsViewedRequest,
    OutputViewedRequest,
)
from onyx.server.features.build.session.output_cards import (
    capture_turn_outputs,
    persist_turn_outputs,
)


def manifest(**files: int) -> OutputsManifestResponse:
    return OutputsManifestResponse(
        entries=[
            OutputsManifestEntry(
                path=path, size=10, mtime_ns=revision, ctime_ns=revision
            )
            for path, revision in files.items()
        ]
    )


def persist_capture(
    db_session: Session,
    session: BuildSession,
    turn: int,
    before: OutputsManifestResponse,
    after: OutputsManifestResponse,
    *,
    owns_turn: Callable[[], bool],
) -> None:
    manager = Mock(spec=SandboxManager)
    manager.get_outputs_manifest.side_effect = [before, after]
    snapshot = capture_turn_outputs(manager, uuid4(), session.id, turn)
    if snapshot is not None:
        persist_turn_outputs(db_session, manager, snapshot, owns_turn=owns_turn)


# Turn attribution and reload.
def test_output_capture_survives_reload_and_only_moves_changed_files(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    files = manifest(
        **{"notes.md": 1, "report.pdf": 1, "web/app/page.tsx": 1, "web/package.json": 1}
    )
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    db_session.expire_all()
    cards = get_output_cards(session.id, test_user, db_session).cards
    assert len(cards) == 3
    assert {card.path for card in cards} == {
        "outputs/notes.md",
        "outputs/report.pdf",
        "outputs/web",
    }
    assert all(card.revision == 1 and card.turn_index == 0 for card in cards)
    newer = manifest(
        **{"notes.md": 2, "report.pdf": 1, "web/app/page.tsx": 2, "web/package.json": 1}
    )
    persist_capture(db_session, session, 1, files, newer, owns_turn=lambda: True)
    # Replaying the same final capture does not increment revisions.
    persist_capture(db_session, session, 1, files, newer, owns_turn=lambda: True)
    db_session.expire_all()
    by_path = {
        card.path: card
        for card in get_output_cards(session.id, test_user, db_session).cards
    }
    assert (
        by_path["outputs/notes.md"].turn_index,
        by_path["outputs/notes.md"].revision,
    ) == (1, 2)
    assert (by_path["outputs/web"].turn_index, by_path["outputs/web"].revision) == (
        1,
        2,
    )
    assert (
        by_path["outputs/report.pdf"].turn_index,
        by_path["outputs/report.pdf"].revision,
    ) == (0, 1)


@pytest.mark.parametrize("failure", ["before", "after", "owner", "old_turn"])
def test_uncertain_or_stale_capture_preserves_existing_cards(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
    failure: str,
) -> None:
    session = build_session_with_user()
    files = manifest(**{"report.pdf": 1})
    persist_capture(db_session, session, 2, manifest(), files, owns_turn=lambda: True)
    before, after = files, manifest()
    if failure == "before":
        before = OutputsManifestResponse(entries=[], complete=False)
    if failure == "after":
        after = OutputsManifestResponse(entries=[], complete=False)
    persist_capture(
        db_session,
        session,
        1 if failure == "old_turn" else 3,
        before,
        after,
        owns_turn=lambda: failure != "owner",
    )
    card = get_output_cards(session.id, test_user, db_session).cards[0]
    assert not card.deleted
    assert card.turn_index == 2
    assert card.revision == 1


@pytest.mark.parametrize("failed_capture", ["before", "after"])
def test_complete_inventory_recovers_a_previously_missed_deletion(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
    failed_capture: str,
) -> None:
    session = build_session_with_user()
    files = manifest(**{"report.pdf": 1})
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    before, after = files, manifest()
    incomplete = OutputsManifestResponse(entries=[], complete=False)
    if failed_capture == "before":
        before = incomplete
    else:
        after = incomplete
    persist_capture(db_session, session, 1, before, after, owns_turn=lambda: True)
    assert not get_output_cards(session.id, test_user, db_session).cards[0].deleted

    # The later turn starts after deletion, so neither inventory includes the file.
    persist_capture(
        db_session, session, 2, manifest(), manifest(), owns_turn=lambda: True
    )
    card = get_output_cards(session.id, test_user, db_session).cards[0]
    assert card.deleted
    assert (card.turn_index, card.revision) == (0, 1)


@pytest.mark.parametrize("failed_capture", ["before", "after"])
def test_complete_inventory_recovers_a_recreated_file_without_changing_its_turn(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
    failed_capture: str,
) -> None:
    session = build_session_with_user()
    original = manifest(**{"report.pdf": 1})
    recreated = manifest(**{"report.pdf": 2})
    persist_capture(
        db_session, session, 0, manifest(), original, owns_turn=lambda: True
    )
    persist_capture(
        db_session, session, 1, original, manifest(), owns_turn=lambda: True
    )
    incomplete = OutputsManifestResponse(entries=[], complete=False)
    persist_capture(
        db_session,
        session,
        2,
        incomplete if failed_capture == "before" else manifest(),
        incomplete if failed_capture == "after" else recreated,
        owns_turn=lambda: True,
    )
    assert get_output_cards(session.id, test_user, db_session).cards[0].deleted
    persist_capture(
        db_session, session, 3, recreated, recreated, owns_turn=lambda: True
    )
    persist_capture(
        db_session, session, 4, recreated, recreated, owns_turn=lambda: True
    )
    card = get_output_cards(session.id, test_user, db_session).cards[0]
    assert not card.deleted
    assert card.turn_index == 0
    assert card.revision == 2


# Exact viewed revisions and authorization.
def test_viewed_revision_is_monotonic_and_cannot_clear_newer_output(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    files = manifest(**{"notes.md": 1})
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    card = get_output_cards(session.id, test_user, db_session).cards[0]
    artifact_id = UUID(card.id)
    assert card.viewed_revision is None
    artifact = db_session.get(Artifact, artifact_id)
    assert artifact is not None
    modified_at = artifact.updated_at
    seen = view_output_card(
        session.id, artifact_id, OutputViewedRequest(revision=1), test_user, db_session
    )
    assert seen.viewed_revision == 1
    db_session.expire_all()
    assert artifact.viewed_revision == 1
    assert artifact.updated_at == modified_at
    persist_capture(
        db_session,
        session,
        1,
        files,
        manifest(**{"notes.md": 2}),
        owns_turn=lambda: True,
    )
    late = view_output_card(
        session.id, artifact_id, OutputViewedRequest(revision=1), test_user, db_session
    )
    assert (late.revision, late.viewed_revision) == (2, 1)
    view_output_card(
        session.id, artifact_id, OutputViewedRequest(revision=2), test_user, db_session
    )
    replay = view_output_card(
        session.id, artifact_id, OutputViewedRequest(revision=1), test_user, db_session
    )
    assert replay.viewed_revision == 2
    with pytest.raises(OnyxError) as future:
        view_output_card(
            session.id,
            artifact_id,
            OutputViewedRequest(revision=3),
            test_user,
            db_session,
        )
    assert future.value.status_code == 409
    db_session.rollback()
    stranger = User(id=uuid4())
    with pytest.raises(OnyxError) as denied:
        get_output_cards(session.id, stranger, db_session)
    assert denied.value.status_code == 404
    with pytest.raises(OnyxError) as denied_view:
        view_output_card(
            session.id,
            artifact_id,
            OutputViewedRequest(revision=2),
            stranger,
            db_session,
        )
    assert denied_view.value.status_code == 404
    other_session = build_session_with_user()
    with pytest.raises(OnyxError) as wrong_session:
        view_output_card(
            other_session.id,
            artifact_id,
            OutputViewedRequest(revision=2),
            test_user,
            db_session,
        )
    assert wrong_session.value.status_code == 404


def test_deleted_output_stays_in_its_original_turn(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    files = manifest(**{"notes.md": 1})
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    persist_capture(db_session, session, 1, files, manifest(), owns_turn=lambda: True)
    card = get_output_cards(session.id, test_user, db_session).cards[0]
    assert card.deleted
    assert card.turn_index == 0
    persist_capture(db_session, session, 2, manifest(), files, owns_turn=lambda: True)
    restored = get_output_cards(session.id, test_user, db_session).cards[0]
    assert not restored.deleted
    assert restored.revision == 2
    assert restored.turn_index == 2


@pytest.mark.parametrize("file_count", [1, 40])
def test_lost_ownership_during_database_writes_rolls_back_all_cards(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
    file_count: int,
) -> None:
    session = build_session_with_user()
    before = manifest(**{"original.md": 1})
    persist_capture(db_session, session, 0, manifest(), before, owns_turn=lambda: True)
    after = manifest(**{f"new-{index}.md": 2 for index in range(file_count)})
    ownership = iter([True, True, False])
    persist_capture(
        db_session, session, 1, before, after, owns_turn=lambda: next(ownership)
    )
    # A later caller commit must not publish the abandoned partial batch.
    db_session.commit()
    db_session.expire_all()
    cards = get_output_cards(session.id, test_user, db_session).cards
    assert len(cards) == 1
    assert cards[0].path == "outputs/original.md"
    assert cards[0].turn_index == 0
    assert not cards[0].deleted


def test_bulk_viewed_uses_exact_revisions_and_session_owner(
    db_session: Session,
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    other = build_session_with_user()
    initial = manifest(**{"one.md": 1, "nested/two.md": 1})
    persist_capture(db_session, session, 0, manifest(), initial, owns_turn=lambda: True)
    persist_capture(
        db_session,
        other,
        0,
        manifest(),
        manifest(**{"other.md": 1}),
        owns_turn=lambda: True,
    )
    cards = get_output_cards(session.id, test_user, db_session).cards
    foreign = get_output_cards(other.id, test_user, db_session).cards[0]
    persist_capture(
        db_session,
        session,
        1,
        initial,
        manifest(**{"one.md": 2, "nested/two.md": 1}),
        owns_turn=lambda: True,
    )
    request = OutputsViewedRequest(
        revisions={UUID(card.id): card.revision for card in [*cards, foreign]}
    )
    with pytest.raises(OnyxError):
        view_output_cards(session.id, request, User(id=uuid4()), db_session)
    # Reject the whole request before acknowledging any valid entries.
    future = dict(request.revisions)
    future[UUID(cards[0].id)] = 100
    with pytest.raises(OnyxError) as conflict:
        view_output_cards(
            session.id, OutputsViewedRequest(revisions=future), test_user, db_session
        )
    assert conflict.value.status_code == 409
    db_session.commit()
    assert all(
        card.viewed_revision is None
        for card in get_output_cards(session.id, test_user, db_session).cards
    )
    result = view_output_cards(session.id, request, test_user, db_session)
    assert len(result.cards) == 2
    assert all(card.viewed_revision == 1 for card in result.cards)
    newer = next(card for card in result.cards if card.path == "outputs/one.md")
    assert newer.revision == 2
    assert (
        get_output_cards(other.id, test_user, db_session).cards[0].viewed_revision
        is None
    )
    # A stale acknowledgement cannot lower a later viewed revision.
    view_output_cards(
        session.id,
        OutputsViewedRequest(revisions={UUID(newer.id): 2}),
        test_user,
        db_session,
    )
    repeated = view_output_cards(session.id, request, test_user, db_session)
    assert (
        next(card for card in repeated.cards if card.id == newer.id).viewed_revision
        == 2
    )


def test_bulk_viewed_locks_in_capture_path_order(
    db_session: Session,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    session_id = session.id
    files = manifest(**{"Z.md": 1, "a.md": 1})
    persist_capture(db_session, session, 0, manifest(), files, owns_turn=lambda: True)
    artifacts = list(
        db_session.scalars(select(Artifact).where(Artifact.session_id == session_id))
    )
    artifacts.sort(key=lambda artifact: artifact.path)
    ids = sorted([uuid4(), uuid4()], reverse=True)
    for artifact, artifact_id in zip(artifacts, ids, strict=True):
        artifact.id = artifact_id
    db_session.commit()
    worker_pid: Queue[int] = Queue()

    def acknowledge() -> None:
        with Session(db_session.get_bind()) as worker:
            pid = worker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            worker_pid.put(pid)
            mark_outputs_viewed(
                worker, session_id=session_id, revisions=dict.fromkeys(ids, 1)
            )
            worker.commit()

    # Hold the first capture row. Bulk viewed must wait here without locking the second.
    db_session.execute(
        select(Artifact.id).where(Artifact.id == ids[0]).with_for_update()
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(acknowledge)
        try:
            pid = worker_pid.get(timeout=5)
            deadline = time.monotonic() + 5
            while not db_session.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}
            ):
                assert time.monotonic() < deadline, (
                    "viewed request did not wait for capture"
                )
                time.sleep(0.01)
            db_session.execute(
                select(Artifact.id)
                .where(Artifact.id == ids[1])
                .with_for_update(nowait=True)
            )
        finally:
            db_session.rollback()
        future.result(timeout=5)
