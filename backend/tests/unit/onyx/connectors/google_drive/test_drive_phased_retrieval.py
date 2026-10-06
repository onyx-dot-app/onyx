"""Phased service account retrieval against an in-memory tenant.

The tenant covers the cases the redesign exists for: a limited-access folder
only a drive organizer sees, an organizer reached through a group, a drive with
no organizer, a drive nobody can list, shortcuts into covered scopes, a file
shared with several users, and a user whose impersonation fails.
"""

from collections import Counter
from unittest.mock import patch

import pytest

from onyx.connectors.google_drive import connector as connector_mod
from onyx.connectors.google_drive.connector import (
    GoogleDriveConnector,
    UnreachableTargetsError,
)
from onyx.connectors.google_drive.drive_access import (
    DriveMember,
    DriveRole,
    PrincipalType,
)
from onyx.connectors.google_drive.models import (
    DriveRetrievalPhase,
    DriveRetrievalStage,
    RetrievedDriveFile,
    StageCompletion,
)
from onyx.connectors.google_utils.resources import ImpersonationError
from onyx.connectors.models import SlimDocument
from onyx.utils.threadpool_concurrency import ThreadSafeDict
from tests.unit.onyx.connectors.google_drive.fake_drive import (
    DOMAIN,
    FakeTenant,
    Folder,
    SharedDrive,
    drive_file,
    make_service_account_connector,
    run_one_call,
    run_to_completion,
)

ADMIN = f"admin@{DOMAIN}"
ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"
CAROL = f"carol@{DOMAIN}"
GROUP = f"managers@{DOMAIN}"
EXTERNAL = "someone@other.com"


def _member(email: str, role: DriveRole, kind: PrincipalType) -> DriveMember:
    return DriveMember(email=email, principal_type=kind, role=role)


def _org_tenant() -> FakeTenant:
    user = PrincipalType.USER
    return FakeTenant(
        users=[ADMIN, ALICE, BOB, CAROL],
        groups={GROUP: [BOB]},
        broken_users={CAROL},
        shared_drives={
            # r1 sits in a limited-access folder: only the organizer sees it.
            "d1": SharedDrive(
                members=[
                    _member(ALICE, DriveRole.ORGANIZER, user),
                    _member(BOB, DriveRole.READER, user),
                ],
                files=["d1f1", "d1f2", "d1f3", "d1f4", "d1f5"],
                restricted_files=["r1"],
            ),
            # Organizer is a group; bob is its only member.
            "d2": SharedDrive(
                members=[_member(GROUP, DriveRole.ORGANIZER, PrincipalType.GROUP)],
                files=["d2f1", "d2f2", "d2f3"],
            ),
            # No organizer: listed by a reader, so it stays incomplete.
            "d3": SharedDrive(
                members=[_member(BOB, DriveRole.READER, user)],
                files=["d3f1", "d3f2"],
            ),
            # Managed only from outside the domain: nobody here can list it.
            "d4": SharedDrive(
                members=[_member(EXTERNAL, DriveRole.ORGANIZER, user)],
                files=["d4f1"],
            ),
        },
        my_drive={
            ADMIN: [drive_file("adm1", owner=ADMIN)],
            ALICE: [
                drive_file("a1", owner=ALICE),
                drive_file("a2", owner=ALICE),
                drive_file("a3", owner=ALICE),
                # Shortcut targets: one into a covered drive, one to bob's file.
                drive_file("d1f1", drive_id="d1"),
                drive_file("b1", owner=BOB),
                drive_file("a4", owner=ALICE),
            ],
            BOB: [drive_file("b1", owner=BOB), drive_file("b2", owner=BOB)],
            CAROL: [drive_file("c1", owner=CAROL)],
        },
        shared_with={
            ADMIN: [drive_file("x2", owner=EXTERNAL)],
            ALICE: [
                drive_file("b1", owner=BOB),
                drive_file("c1", owner=CAROL),
                drive_file("x1", owner=EXTERNAL),
                drive_file("d3f1", drive_id="d3"),
                drive_file("d1f2", drive_id="d1"),
            ],
            BOB: [
                drive_file("a1", owner=ALICE),
                drive_file("x1", owner=EXTERNAL),
                drive_file("c1", owner=CAROL),
            ],
        },
    )


_EXPECTED_ORG_FILES = {
    *("d1f1", "d1f2", "d1f3", "d1f4", "d1f5", "r1"),
    *("d2f1", "d2f2", "d2f3"),
    *("d3f1", "d3f2"),
    *("adm1", "a1", "a2", "a3", "a4", "b1", "b2"),
    # carol's own pass failed, so her file arrives through a share.
    "c1",
    *("x1", "x2"),
}


def _full_org_connector() -> GoogleDriveConnector:
    return make_service_account_connector(
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=True,
    )


@pytest.mark.parametrize(
    ("pages_per_call", "partitions_per_call"),
    [(1, 1), (1, 3), (2, 4), (100, 100)],
)
def test_each_file_is_yielded_exactly_once(
    pages_per_call: int, partitions_per_call: int
) -> None:
    """The yielded set is the same however often the run checkpoints, and
    every checkpoint survives a JSON round trip between calls."""
    tenant = _org_tenant()
    connector = _full_org_connector()

    with (
        tenant.patch(connector),
        patch.object(
            connector_mod, "SHARED_DRIVE_PAGES_PER_CHECKPOINT", pages_per_call
        ),
        patch.object(connector_mod, "MY_DRIVE_PAGES_PER_CHECKPOINT", pages_per_call),
        patch.object(connector_mod, "PARTITIONS_PER_CHECKPOINT", partitions_per_call),
    ):
        result = run_to_completion(connector)

    duplicates = {
        file_id: count
        for file_id, count in Counter(result.file_ids).items()
        if count > 1
    }
    assert duplicates == {}
    assert set(result.file_ids) == _EXPECTED_ORG_FILES
    assert [error.user_email for error in result.errors] == [CAROL]
    assert isinstance(result.errors[0].error, ImpersonationError)


def test_restricted_folder_is_listed_by_the_organizer() -> None:
    tenant = _org_tenant()
    connector = _full_org_connector()

    with tenant.patch(connector):
        result = run_to_completion(connector)

    final = result.checkpoints[-1]
    assert "r1" in result.file_ids
    assert final.organizer_email_by_drive_id["d1"] == ALICE
    # Reached through the group, and complete because the group is organizer.
    assert final.organizer_email_by_drive_id["d2"] == BOB
    assert final.incomplete_drive_ids == {"d3", "d4"}
    assert "d4" not in final.organizer_email_by_drive_id
    assert final.failed_impersonation_emails == {CAROL}


def test_interrupted_call_loses_nothing() -> None:
    """A call that dies mid-stream never saves its checkpoint. Retrying from
    the last saved one must still reach every file."""
    tenant = _org_tenant()
    connector = _full_org_connector()
    seen: set[str] = set()

    with (
        tenant.patch(connector),
        patch.object(connector_mod, "SHARED_DRIVE_PAGES_PER_CHECKPOINT", 1),
        patch.object(connector_mod, "MY_DRIVE_PAGES_PER_CHECKPOINT", 1),
        patch.object(connector_mod, "PARTITIONS_PER_CHECKPOINT", 1),
    ):
        checkpoint = connector.build_dummy_checkpoint()
        for _ in range(200):
            saved_json = checkpoint.model_dump_json()
            # First attempt: take one item, then crash before the checkpoint
            # is returned.
            output = connector.load_from_checkpoint(0, 2_000_000_000, checkpoint)
            first = next(output, None)
            # Conversion is patched out, so the stream carries retrieved files.
            if isinstance(first, RetrievedDriveFile) and first.error is None:
                seen.add(first.drive_file["id"])
            output.close()

            retry = connector.validate_checkpoint_json(saved_json)
            items, checkpoint = run_one_call(connector, retry)
            seen.update(item.drive_file["id"] for item in items if item.error is None)
            checkpoint = connector.validate_checkpoint_json(
                checkpoint.model_dump_json()
            )
            if not checkpoint.has_more:
                break

    assert seen == _EXPECTED_ORG_FILES


def test_checkpoint_size_does_not_grow_with_document_count() -> None:
    """The regression the redesign exists for: exact partitions keep no
    per-document state, so ten times the files leaves the checkpoint flat."""

    def _largest_checkpoint(num_files: int) -> int:
        tenant = FakeTenant(
            users=[ADMIN, ALICE],
            shared_drives={
                "d1": SharedDrive(
                    members=[_member(ALICE, DriveRole.ORGANIZER, PrincipalType.USER)],
                    files=[f"d1-{i}" for i in range(num_files)],
                )
            },
            my_drive={
                ALICE: [drive_file(f"a-{i}", owner=ALICE) for i in range(num_files)]
            },
        )
        connector = make_service_account_connector(
            include_shared_drives=True, include_my_drives=True
        )
        with (
            tenant.patch(connector),
            patch.object(connector_mod, "SHARED_DRIVE_PAGES_PER_CHECKPOINT", 25),
            patch.object(connector_mod, "MY_DRIVE_PAGES_PER_CHECKPOINT", 25),
        ):
            result = run_to_completion(connector, max_calls=5_000)
        assert len(result.file_ids) == 2 * num_files
        return max(len(cp.model_dump_json()) for cp in result.checkpoints)

    small = _largest_checkpoint(100)
    large = _largest_checkpoint(1_000)

    # Page tokens carry an offset, so allow a few bytes of digits.
    assert large - small < 50


def test_owner_pass_suppresses_shared_copies_but_not_a_failed_owners() -> None:
    tenant = _org_tenant()
    connector = _full_org_connector()

    with tenant.patch(connector):
        result = run_to_completion(connector)

    sources = Counter(result.file_ids)
    # b1 is shared with alice and reached by her shortcut; bob's pass owns it.
    assert sources["b1"] == 1
    # carol could not be impersonated, so alice's share is the one that counts.
    assert sources["c1"] == 1


def test_old_stage_checkpoint_restarts_with_phases() -> None:
    tenant = _org_tenant()
    connector = _full_org_connector()
    old = connector.build_dummy_checkpoint()
    old.completion_stage = DriveRetrievalStage.MY_DRIVE_FILES
    old.user_emails = [ADMIN, ALICE]
    old.drive_ids_to_retrieve = ["d1"]
    old.folder_ids_to_retrieve = []
    old.completion_map = ThreadSafeDict(
        {
            ALICE: StageCompletion(
                stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
                completed_until=0,
                current_folder_or_drive_id="d1",
                next_page_token="token-from-the-old-loop",
            )
        }
    )
    old = connector.validate_checkpoint_json(old.model_dump_json())

    with tenant.patch(connector):
        result = run_to_completion(connector, checkpoint=old)

    assert set(result.file_ids) == _EXPECTED_ORG_FILES
    assert result.checkpoints[-1].phase_progress is not None
    assert result.checkpoints[-1].phase_progress.phase is DriveRetrievalPhase.DONE


# --- requested folders -------------------------------------------------------


def _folder_tenant() -> FakeTenant:
    return FakeTenant(
        users=[ADMIN, ALICE, BOB],
        folders={
            # Externally owned: each user sees a different limited subfolder,
            # so only the union of both crawls is complete.
            "fext": Folder(
                owner=EXTERNAL,
                drive_id=None,
                visible_files={ALICE: ["e1", "e2"], BOB: ["e2", "e3"]},
                permission_emails=[ALICE, BOB, EXTERNAL],
            ),
            # In bob's My Drive: bob as owner sees everything.
            "fbob": Folder(
                owner=BOB,
                drive_id=None,
                visible_files={BOB: ["fb1", "fb2"], ALICE: ["fb1"]},
            ),
            # Nested inside fbob and requested too.
            "fsub": Folder(
                owner=BOB,
                drive_id=None,
                visible_files={BOB: ["fb2"]},
            ),
        },
    )


def _folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def test_requested_folders_use_owner_or_union() -> None:
    tenant = _folder_tenant()
    connector = make_service_account_connector(
        shared_folder_urls=",".join(_folder_url(f) for f in ("fext", "fbob", "fsub"))
    )

    with tenant.patch(connector):
        result = run_to_completion(connector)

    assert Counter(result.file_ids) == Counter(
        {"e1": 1, "e2": 1, "e3": 1, "fb1": 1, "fb2": 1}
    )
    assert result.checkpoints[-1].unreachable_target_ids == set()


def test_unreachable_target_blocks_pruning_but_not_perm_sync() -> None:
    tenant = _folder_tenant()
    connector = make_service_account_connector(
        shared_folder_urls=",".join(_folder_url(f) for f in ("fbob", "fgone"))
    )

    with (
        tenant.patch(connector),
        patch.object(connector, "_get_new_ancestors_for_files", return_value=[]),
        patch.object(
            connector_mod,
            "build_slim_document",
            side_effect=lambda _creds, file, *_args, **_kwargs: SlimDocument(
                id=file["id"]
            ),
        ),
    ):
        with pytest.raises(UnreachableTargetsError, match="fgone"):
            list(connector.retrieve_all_slim_docs())

        batches = list(connector.retrieve_all_slim_docs_perm_sync())

    slim_ids = {
        doc.id for batch in batches for doc in batch if isinstance(doc, SlimDocument)
    }
    assert slim_ids == {"fb1", "fb2"}


def test_specific_user_emails_limit_who_is_impersonated() -> None:
    """With specific_user_emails set, the connector acts only as those users:
    not the admin, and not an organizer outside the list."""
    tenant = _org_tenant()
    tenant.users = [BOB]
    tenant.folders["fadmin"] = Folder(
        owner=ADMIN, drive_id=None, visible_files={ADMIN: ["secret"]}
    )
    connector = make_service_account_connector(
        shared_drive_urls="https://drive.google.com/drive/folders/d1",
        shared_folder_urls=_folder_url("fadmin"),
        specific_user_emails=BOB,
    )

    with tenant.patch(connector):
        result = run_to_completion(connector)

    final = result.checkpoints[-1]
    # bob is only a reader of d1, so the organizer-only file stays hidden.
    assert set(result.file_ids) == {"d1f1", "d1f2", "d1f3", "d1f4", "d1f5"}
    assert final.organizer_email_by_drive_id["d1"] == BOB
    assert final.incomplete_drive_ids == {"d1"}
    assert final.unreachable_target_ids == {"fadmin"}
