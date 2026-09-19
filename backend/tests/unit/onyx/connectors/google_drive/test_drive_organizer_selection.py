"""Picking the identity to impersonate for a shared drive.

Only an organizer is guaranteed to see limited-access folders, so selection
prefers one and marks the result incomplete when it has to settle for less.
"""

from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from onyx.connectors.google_drive.drive_access import (
    DriveMember,
    DriveReachability,
    DriveRole,
    OrganizerChoice,
    PrincipalType,
    check_drive_reachable,
    list_drive_members,
    select_drive_organizer,
)

_DOMAIN = "onyx-test.com"
_DRIVE = "drive_1"
_MOD = "onyx.connectors.google_drive.drive_access"


def _member(
    email: str | None,
    role: DriveRole,
    principal_type: PrincipalType = PrincipalType.USER,
) -> DriveMember:
    return DriveMember(email=email, principal_type=principal_type, role=role)


def _select(
    members: list[DriveMember],
    groups: dict[str, list[str]] | None = None,
    listable: set[str] | None = None,
) -> OrganizerChoice:
    """listable=None means every candidate can list the drive."""
    return select_drive_organizer(
        drive_id=_DRIVE,
        members=members,
        google_domain=_DOMAIN,
        expand_group=lambda email: (groups or {}).get(email, []),
        can_list_drive=lambda email: listable is None or email in listable,
    )


def test_prefers_an_in_domain_user_organizer() -> None:
    choice = _select(
        [
            _member(f"reader@{_DOMAIN}", DriveRole.READER),
            _member(f"boss@{_DOMAIN}", DriveRole.ORGANIZER),
        ]
    )

    assert choice.email == f"boss@{_DOMAIN}"
    assert choice.role is DriveRole.ORGANIZER
    assert choice.complete is True


def test_expands_a_group_organizer_into_members() -> None:
    choice = _select(
        [_member("team@" + _DOMAIN, DriveRole.ORGANIZER, PrincipalType.GROUP)],
        groups={f"team@{_DOMAIN}": [f"member@{_DOMAIN}"]},
    )

    assert choice.email == f"member@{_DOMAIN}"
    assert choice.complete is True


def test_direct_organizer_outranks_a_group_organizer() -> None:
    """Sorting the two pools together would let a group member win on alphabet."""
    choice = _select(
        [
            _member(f"zeta@{_DOMAIN}", DriveRole.ORGANIZER),
            _member(f"team@{_DOMAIN}", DriveRole.ORGANIZER, PrincipalType.GROUP),
        ],
        groups={f"team@{_DOMAIN}": [f"alpha@{_DOMAIN}"]},
    )

    assert choice.email == f"zeta@{_DOMAIN}"


def test_direct_organizer_is_used_when_group_expansion_fails() -> None:
    """A Directory API outage must not block a usable direct organizer."""

    def exploding_expand(_email: str) -> list[str]:
        raise RuntimeError("directory api down")

    choice = select_drive_organizer(
        drive_id=_DRIVE,
        members=[
            _member(f"boss@{_DOMAIN}", DriveRole.ORGANIZER),
            _member(f"team@{_DOMAIN}", DriveRole.ORGANIZER, PrincipalType.GROUP),
        ],
        google_domain=_DOMAIN,
        expand_group=exploding_expand,
        can_list_drive=lambda _email: True,
    )

    assert choice.email == f"boss@{_DOMAIN}"


def test_group_expansion_failure_falls_through_to_a_lesser_role() -> None:
    def exploding_expand(_email: str) -> list[str]:
        raise RuntimeError("directory api down")

    choice = select_drive_organizer(
        drive_id=_DRIVE,
        members=[
            _member(f"team@{_DOMAIN}", DriveRole.ORGANIZER, PrincipalType.GROUP),
            _member(f"writer@{_DOMAIN}", DriveRole.WRITER),
        ],
        google_domain=_DOMAIN,
        expand_group=exploding_expand,
        can_list_drive=lambda _email: True,
    )

    assert choice.email == f"writer@{_DOMAIN}"
    assert choice.complete is False


def test_skips_external_organizers() -> None:
    """An account outside the domain cannot be impersonated at all."""
    choice = _select(
        [
            _member("outsider@gmail.com", DriveRole.ORGANIZER),
            _member(f"writer@{_DOMAIN}", DriveRole.WRITER),
        ]
    )

    assert choice.email == f"writer@{_DOMAIN}"
    assert choice.role is DriveRole.WRITER
    # No organizer was reachable, so restricted folders may be missed.
    assert choice.complete is False


def test_falls_back_by_role_when_no_organizer_exists() -> None:
    choice = _select(
        [
            _member(f"reader@{_DOMAIN}", DriveRole.READER),
            _member(f"content@{_DOMAIN}", DriveRole.FILE_ORGANIZER),
        ]
    )

    assert choice.email == f"content@{_DOMAIN}"
    assert choice.role is DriveRole.FILE_ORGANIZER
    assert choice.complete is False


def test_moves_on_when_the_organizer_cannot_actually_list() -> None:
    """A named organizer can still fail to impersonate; verify before committing."""
    choice = _select(
        [
            _member(f"suspended@{_DOMAIN}", DriveRole.ORGANIZER),
            _member(f"working@{_DOMAIN}", DriveRole.ORGANIZER),
        ],
        listable={f"working@{_DOMAIN}"},
    )

    assert choice.email == f"working@{_DOMAIN}"
    assert choice.complete is True


def test_reports_no_principal_when_nothing_is_impersonable() -> None:
    choice = _select([_member("outsider@gmail.com", DriveRole.ORGANIZER)])

    assert choice.email is None
    assert choice.complete is False


def test_selection_is_stable_across_member_order() -> None:
    """A resumed run must choose the same organizer as the original."""
    members = [
        _member(f"b@{_DOMAIN}", DriveRole.ORGANIZER),
        _member(f"a@{_DOMAIN}", DriveRole.ORGANIZER),
    ]

    assert _select(members).email == _select(list(reversed(members))).email


def _service_raising(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    service = MagicMock()
    service.drives().get().execute.side_effect = HttpError(resp, b"boom")
    return service


def test_missing_drive_is_unreachable_not_empty() -> None:
    """shared_drive_3 lists zero files but 404s on drives.get.

    Reading that as an empty drive would prune everything indexed from it.
    """
    assert (
        check_drive_reachable(_service_raising(404), _DRIVE)
        is DriveReachability.UNREACHABLE
    )


@pytest.mark.parametrize("status", [403, 500])
def test_other_errors_are_unknown_rather_than_unreachable(status: int) -> None:
    assert (
        check_drive_reachable(_service_raising(status), _DRIVE)
        is DriveReachability.UNKNOWN
    )


def test_successful_get_is_reachable() -> None:
    assert check_drive_reachable(MagicMock(), _DRIVE) is DriveReachability.REACHABLE


def test_members_with_unrecognized_role_or_type_are_skipped() -> None:
    """Google can add roles; an unknown one must not crash discovery."""
    raw = [
        {"emailAddress": f"boss@{_DOMAIN}", "type": "user", "role": "organizer"},
        {"emailAddress": f"odd@{_DOMAIN}", "type": "user", "role": "brandNewRole"},
        {"type": "domain", "domain": _DOMAIN, "role": "reader"},
    ]
    with patch(
        f"{_MOD}.execute_paginated_retrieval", return_value=iter(raw)
    ) as retrieval:
        members = list_drive_members(MagicMock(), _DRIVE)

    assert [(m.email, m.role, m.principal_type) for m in members] == [
        (f"boss@{_DOMAIN}", DriveRole.ORGANIZER, PrincipalType.USER),
        (None, DriveRole.READER, PrincipalType.DOMAIN),
    ]
    # Domain admin access is the whole reason this works for drives the admin
    # is not a member of; without it files.list would 403 and discovery stops.
    assert retrieval.call_args.kwargs["useDomainAdminAccess"] is True
    assert retrieval.call_args.kwargs["supportsAllDrives"] is True
    assert retrieval.call_args.kwargs["fileId"] == _DRIVE


def test_foreign_domain_drive_yields_no_members() -> None:
    """Domain admin access only covers our own drives; elsewhere it 404s."""
    resp = MagicMock()
    resp.status = 404
    with patch(
        f"{_MOD}.execute_paginated_retrieval",
        side_effect=HttpError(resp, b"not found"),
    ):
        assert list_drive_members(MagicMock(), _DRIVE) == []


@pytest.mark.parametrize("status", [403, 500])
def test_unexpected_member_lookup_errors_are_not_silently_empty(status: int) -> None:
    """An auth or server error is not evidence that a drive has no members.

    Returning [] here would make selection report "no impersonable principal"
    and skip the drive without surfacing the failure.
    """
    resp = MagicMock()
    resp.status = status
    with patch(
        f"{_MOD}.execute_paginated_retrieval",
        side_effect=HttpError(resp, b"boom"),
    ):
        with pytest.raises(HttpError):
            list_drive_members(MagicMock(), _DRIVE)
