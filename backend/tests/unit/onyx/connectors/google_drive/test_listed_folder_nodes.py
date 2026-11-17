"""Hierarchy nodes from the folder shards of the parallel listing. A folder
that one user lists with no parent gets its parent from a later copy or from
a read after the listing. A folder shared only by link is a node only as the
parent of another node."""

from typing import Any

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.models import (
    DriveListingState,
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    RetrievedDriveFile,
)
from onyx.connectors.models import HierarchyNode

_LISTER = "user1@x.com"


def _connector(exclude_domain_link_only: bool = False) -> GoogleDriveConnector:
    return GoogleDriveConnector(
        include_shared_drives=True,
        exclude_domain_link_only=exclude_domain_link_only,
    )


def _checkpoint(connector: GoogleDriveConnector) -> GoogleDriveCheckpoint:
    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.listing = DriveListingState(window_t0=0, window_t1=1)
    return checkpoint


def _folder(
    folder_id: str, parent_id: str | None = None, link_only: bool = False
) -> RetrievedDriveFile:
    drive_file: GoogleDriveFileType = {
        "id": folder_id,
        "name": folder_id,
        "mimeType": DRIVE_FOLDER_TYPE,
    }
    if parent_id is not None:
        drive_file["parents"] = [parent_id]
    if link_only:
        drive_file["permissions"] = [
            {"type": "domain", "role": "reader", "allowFileDiscovery": False}
        ]
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
        drive_file=drive_file,
        user_email=_LISTER,
    )


def _nodes(
    connector: GoogleDriveConnector,
    checkpoint: GoogleDriveCheckpoint,
    folders: list[RetrievedDriveFile],
) -> list[HierarchyNode]:
    listing = checkpoint.listing
    assert listing is not None
    return connector._listed_folder_nodes(
        listing, checkpoint, folders, [], None, add_prefix=False
    )


def _readers(listing: DriveListingState) -> dict[str, list[str]]:
    return {
        parent_id: listing.parent_reader_emails(parent)
        for parent_id, parent in listing.unresolved_parents.items()
    }


def test_a_later_copy_gives_a_parentless_folder_its_parent() -> None:
    connector = _connector()
    checkpoint = _checkpoint(connector)

    first = _nodes(connector, checkpoint, [_folder("shared")])
    again = _nodes(connector, checkpoint, [_folder("shared")])
    repaired = _nodes(connector, checkpoint, [_folder("shared", parent_id="top")])

    assert [(node.raw_node_id, node.raw_parent_id) for node in first] == [
        ("shared", None)
    ]
    assert again == []
    assert [(node.raw_node_id, node.raw_parent_id) for node in repaired] == [
        ("shared", "top")
    ]
    listing = checkpoint.listing
    assert listing is not None
    assert listing.parentless_folder_emails == {}
    # The parent is read after the listing.
    assert _readers(listing) == {"top": [_LISTER]}


def test_a_read_after_the_listing_gives_a_parentless_folder_its_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector()
    checkpoint = _checkpoint(connector)
    _nodes(connector, checkpoint, [_folder("shared")])
    folders: dict[str, GoogleDriveFileType] = {
        "shared": _folder("shared", parent_id="top").drive_file,
        "top": _folder("top").drive_file,
    }

    def read_folder(
        _self: GoogleDriveConnector, folder_id: str, *_args: Any, **_kwargs: Any
    ) -> GoogleDriveFileType | None:
        return folders.get(folder_id)

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: False)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    nodes = [
        (node.raw_node_id, node.raw_parent_id) for batch in batches for node in batch
    ]
    assert nodes == [("shared", "top"), ("top", None)]
    listing = checkpoint.listing
    assert listing is not None
    assert listing.parentless_folder_emails == {}
    assert listing.unresolved_parents == {}


def test_a_link_only_folder_is_a_node_only_as_a_parent() -> None:
    connector = _connector(exclude_domain_link_only=True)
    checkpoint = _checkpoint(connector)

    nodes = _nodes(
        connector,
        checkpoint,
        [
            _folder("link_only", parent_id="top", link_only=True),
            _folder("child", parent_id="link_only"),
        ],
    )

    assert [node.raw_node_id for node in nodes] == ["child"]
    listing = checkpoint.listing
    assert listing is not None
    # The read after the listing yields it, as the parent of "child".
    assert "link_only" in listing.unresolved_parents
    assert "link_only" not in checkpoint.seen_hierarchy_node_raw_ids


def _file_under(parent_id: str, user_email: str) -> RetrievedDriveFile:
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        drive_file={"id": f"file_of_{user_email}", "parents": [parent_id]},
        user_email=user_email,
    )


def test_an_unlisted_parent_is_read_as_a_later_user_who_can_read_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two users see a file under the same unlisted parent. The first one
    cannot read the parent, and the admin cannot. The second one can."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    connector._listed_folder_nodes(
        listing,
        checkpoint,
        [],
        [_file_under("parent", "first@x.com"), _file_under("parent", "second@x.com")],
        None,
        add_prefix=False,
    )
    assert _readers(listing) == {"parent": ["first@x.com", "second@x.com"]}
    read_as: list[str] = []

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        read_as.append(retriever_email)
        if retriever_email != "second@x.com":
            return None
        return _folder(folder_id).drive_file

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: True)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert [node.raw_node_id for batch in batches for node in batch] == ["parent"]
    assert read_as == ["first@x.com", "second@x.com"]


def test_a_read_round_with_no_node_still_yields_a_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer checks its stop signal for each batch, so a round in
    which no folder can be read must give it one."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    _nodes(connector, checkpoint, [_folder("shared")])
    monkeypatch.setattr(
        GoogleDriveConnector, "_get_folder_metadata", lambda *_args, **_kwargs: None
    )

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert batches == [[]]


@pytest.mark.parametrize(
    "old_readers",
    [{"top": _LISTER, "other": [_LISTER]}, {"top": [_LISTER], "other": _LISTER}],
)
def test_a_checkpoint_with_emails_for_each_parent_still_loads(
    old_readers: dict[str, Any],
) -> None:
    state = DriveListingState.model_validate(
        {"window_t0": 0, "window_t1": 1, "unresolved_parent_emails": old_readers}
    )

    assert _readers(state) == {"top": [_LISTER], "other": [_LISTER]}
    assert state.reader_emails == [_LISTER]
    # It saves in the new form and loads back the same.
    again = DriveListingState.model_validate_json(state.model_dump_json())
    assert _readers(again) == _readers(state)


def _service_account(connector: GoogleDriveConnector) -> GoogleDriveConnector:
    connector._is_service_account = True
    connector._primary_admin_email = "admin@x.com"
    return connector


def _file_in(
    parent_id: str,
    user_email: str,
    drive_id: str | None = None,
    owner: str | None = None,
) -> RetrievedDriveFile:
    drive_file: GoogleDriveFileType = {
        "id": f"file_of_{user_email}",
        "parents": [parent_id],
    }
    if drive_id is not None:
        drive_file["driveId"] = drive_id
    if owner is not None:
        drive_file["owners"] = [{"emailAddress": owner}]
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        drive_file=drive_file,
        user_email=user_email,
    )


def _read_as(
    monkeypatch: pytest.MonkeyPatch, can_read: dict[str, set[str]]
) -> list[tuple[str, str]]:
    """Folder reads go to ``can_read`` (folder -> users who can read it).
    Returns the reads in order."""
    reads: list[tuple[str, str]] = []

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        reads.append((folder_id, retriever_email))
        if retriever_email not in can_read.get(folder_id, set()):
            return None
        return _folder(folder_id).drive_file

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: True)
    return reads


@pytest.mark.parametrize(
    "child, first_reader",
    [
        (_file_in("parent", "viewer@x.com", drive_id="drive"), "organizer@x.com"),
        (_file_in("parent", "viewer@x.com", owner="owner@x.com"), "owner@x.com"),
    ],
    ids=["shared_drive_organizer", "my_drive_owner"],
)
def test_an_unlisted_parent_is_read_first_as_its_organizer_or_owner(
    monkeypatch: pytest.MonkeyPatch, child: RetrievedDriveFile, first_reader: str
) -> None:
    connector = _service_account(_connector())
    checkpoint = _checkpoint(connector)
    checkpoint.organizer_email_by_drive_id = {"drive": "organizer@x.com"}
    listing = checkpoint.listing
    assert listing is not None
    connector._listed_folder_nodes(listing, checkpoint, [], [child], None, False)
    reads = _read_as(monkeypatch, {"parent": {first_reader, "viewer@x.com"}})

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert [node.raw_node_id for batch in batches for node in batch] == ["parent"]
    assert reads == [("parent", first_reader)]


def test_an_owner_outside_the_domain_is_not_read_as() -> None:
    connector = _service_account(_connector())
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    connector._listed_folder_nodes(
        listing,
        checkpoint,
        [],
        [_file_in("parent", "viewer@x.com", owner="someone@gmail.com")],
        None,
        False,
    )

    (parent,) = listing.unresolved_parents.values()
    assert connector._parent_readers(checkpoint, listing, parent) == ["viewer@x.com"]


def test_every_user_who_saw_a_child_can_read_an_unlisted_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many users see a child. Only the last one can read the parent."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    users = [f"user{index}@x.com" for index in range(12)]
    connector._listed_folder_nodes(
        listing,
        checkpoint,
        [],
        [_file_in("parent", user) for user in users],
        None,
        add_prefix=False,
    )
    reads = _read_as(monkeypatch, {"parent": {users[-1]}})

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert [node.raw_node_id for batch in batches for node in batch] == ["parent"]
    assert [email for _folder_id, email in reads] == users


def test_a_folder_that_one_reader_cannot_read_is_read_again_as_a_later_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One read round has the parent P (seen by user_a) and its child C (seen
    by user_b). user_a cannot read P. The read of C names P again, with
    user_b, who can read it."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    listing.add_parent_reader("P", "user_a@x.com")
    listing.add_parent_reader("C", "user_b@x.com")
    folders: dict[str, GoogleDriveFileType] = {
        "P": _folder("P").drive_file,
        "C": _folder("C", parent_id="P").drive_file,
    }
    can_read = {"P": {"user_b@x.com"}, "C": {"user_b@x.com"}}

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        if retriever_email not in can_read[folder_id]:
            return None
        return folders[folder_id]

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: False)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    nodes = sorted(node.raw_node_id for batch in batches for node in batch)
    assert nodes == ["C", "P"]


def test_a_folder_read_with_no_parent_is_read_again_as_the_next_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """user_a (and the admin) can read P but cannot see its parent. user_b
    can. The read goes on to user_b, and P gets its parent."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    listing.add_parent_reader("P", "user_a@x.com")
    listing.add_parent_reader("P", "user_b@x.com")
    reads: list[tuple[str, str]] = []

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        reads.append((folder_id, retriever_email))
        if folder_id == "P" and retriever_email == "user_b@x.com":
            return _folder("P", parent_id="top").drive_file
        return _folder(folder_id).drive_file

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: False)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    nodes = [
        (node.raw_node_id, node.raw_parent_id) for batch in batches for node in batch
    ]
    assert nodes[0] == ("P", "top")
    assert reads[:2] == [("P", "user_a@x.com"), ("P", "user_b@x.com")]
    # The parent is read next, first as the user who saw it.
    assert ("top", "user_b@x.com") in reads


def test_a_folder_read_with_no_parent_is_read_again_for_a_later_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """user_a can read P but cannot see its parent, so P is yielded with no
    parent. The read of P's child C as user_b names P again. user_b can see
    P's parent, so P is yielded again with it."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    listing.add_parent_reader("P", "user_a@x.com")
    listing.add_parent_reader("C", "user_b@x.com")

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        if folder_id == "C":
            return _folder("C", parent_id="P").drive_file
        if folder_id == "P" and retriever_email == "user_b@x.com":
            return _folder("P", parent_id="top").drive_file
        if folder_id == "P":
            return _folder("P").drive_file
        return None

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: False)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    nodes = [
        (node.raw_node_id, node.raw_parent_id) for batch in batches for node in batch
    ]
    assert ("C", "P") in nodes
    # The last node yielded for P has its parent.
    assert [node for node in nodes if node[0] == "P"][-1] == ("P", "top")
