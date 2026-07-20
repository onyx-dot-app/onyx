"""Duck-typed stand-in for box_sdk_gen's BoxClient, covering the managers the
Box connector touches. Backed by real box_sdk_gen schema objects so the
connector exercises the same attribute access paths as against the live API."""

from datetime import datetime
from io import BytesIO

from box_sdk_gen.box.errors import BoxAPIError, RequestInfo, ResponseInfo
from box_sdk_gen.managers.events import GetEventsEventType
from box_sdk_gen.schemas.collaboration import Collaboration
from box_sdk_gen.schemas.collaborations import Collaborations
from box_sdk_gen.schemas.event import Event
from box_sdk_gen.schemas.event_source import EventSource, EventSourceItemTypeField
from box_sdk_gen.schemas.events import Events
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_full import FolderFull
from box_sdk_gen.schemas.group_full import GroupFull
from box_sdk_gen.schemas.group_membership import GroupMembership
from box_sdk_gen.schemas.group_memberships import GroupMemberships
from box_sdk_gen.schemas.groups import Groups
from box_sdk_gen.schemas.items import Items
from box_sdk_gen.schemas.user_full import UserFull
from box_sdk_gen.schemas.user_mini import UserMini
from box_sdk_gen.schemas.users import Users


def make_events_page(file_ids: list[str], next_stream_position: str | None) -> Events:
    """Build enterprise events with the EventSource shape returned by Box."""
    entries = [
        Event(
            source=EventSource(
                item_type=EventSourceItemTypeField.FILE,
                item_id=file_id,
                item_name=f"file-{file_id}",
            )
        )
        for file_id in file_ids
    ]
    return Events(entries=entries, next_stream_position=next_stream_position)


def make_folder_event_page(
    folder_id: str, next_stream_position: str | None = None
) -> Events:
    return Events(
        entries=[
            Event(
                source=EventSource(
                    item_type=EventSourceItemTypeField.FOLDER,
                    item_id=folder_id,
                    item_name=f"folder-{folder_id}",
                )
            )
        ],
        next_stream_position=next_stream_position,
    )


def make_box_api_error(status_code: int) -> BoxAPIError:
    return BoxAPIError(
        request_info=RequestInfo(
            method="GET",
            url="https://api.box.com/2.0/test",
            query_params={},
            headers={},
        ),
        response_info=ResponseInfo(status_code=status_code, headers={}),
        message=f"fake box error (status={status_code})",
    )


class FakeFoldersManager:
    def __init__(
        self,
        folders_by_id: dict[str, FolderFull],
        # (folder_id, marker) -> page of items
        pages: dict[tuple[str, str | None], Items],
        fail_listing_folder_ids: set[str],
    ) -> None:
        self._folders_by_id = folders_by_id
        self._pages = pages
        self._fail_listing_folder_ids = fail_listing_folder_ids
        self.listing_calls: list[tuple[str, str | None]] = []

    def get_folder_by_id(
        self,
        folder_id: str,
        *,
        fields: list[str] | None = None,  # noqa: ARG002
    ) -> FolderFull:
        if folder_id not in self._folders_by_id:
            raise make_box_api_error(404)
        return self._folders_by_id[folder_id]

    def get_folder_items(
        self,
        folder_id: str,
        *,
        fields: list[str] | None = None,  # noqa: ARG002
        usemarker: bool | None = None,  # noqa: ARG002
        marker: str | None = None,
        limit: int | None = None,  # noqa: ARG002
    ) -> Items:
        self.listing_calls.append((folder_id, marker))
        if folder_id in self._fail_listing_folder_ids:
            raise make_box_api_error(503)
        key = (folder_id, marker)
        if key not in self._pages:
            raise make_box_api_error(404)
        return self._pages[key]


class FakeDownloadsManager:
    def __init__(self, file_contents: dict[str, bytes]) -> None:
        self._file_contents = file_contents

    def download_file(self, file_id: str) -> BytesIO:
        if file_id not in self._file_contents:
            raise make_box_api_error(404)
        return BytesIO(self._file_contents[file_id])


class FakeFilesManager:
    def __init__(
        self, files_by_id: dict[str, FileFull], fail_status_by_id: dict[str, int]
    ) -> None:
        self._files_by_id = files_by_id
        self._fail_status_by_id = fail_status_by_id
        self.fetch_calls: list[str] = []

    def get_file_by_id(
        self,
        file_id: str,
        *,
        fields: list[str] | None = None,  # noqa: ARG002
    ) -> FileFull:
        self.fetch_calls.append(file_id)
        if file_id in self._fail_status_by_id:
            raise make_box_api_error(self._fail_status_by_id[file_id])
        if file_id not in self._files_by_id:
            raise make_box_api_error(404)
        return self._files_by_id[file_id]


class FakeEventsManager:
    def __init__(
        self,
        event_pages: list[Events],
        fail_status_by_call: dict[int, int],
    ) -> None:
        # each call returns the next page in order
        self._event_pages = event_pages
        self._fail_status_by_call = fail_status_by_call
        self.calls: list[str | None] = []
        self.created_windows: list[tuple[datetime | None, datetime | None]] = []
        self.event_types: list[list[GetEventsEventType] | None] = []

    def get_events(
        self,
        *,
        stream_type: object = None,  # noqa: ARG002
        event_type: list[GetEventsEventType] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        stream_position: str | None = None,
        limit: int | None = None,  # noqa: ARG002
    ) -> Events:
        self.calls.append(stream_position)
        self.created_windows.append((created_after, created_before))
        self.event_types.append(event_type)
        call_number = len(self.calls)
        if call_number in self._fail_status_by_call:
            raise make_box_api_error(self._fail_status_by_call[call_number])
        index = call_number - 1
        if index < len(self._event_pages):
            return self._event_pages[index]
        return Events(entries=[], next_stream_position=stream_position)


class FakeListCollaborationsManager:
    def __init__(
        self,
        folder_collaborations: dict[str, list[Collaboration]],
        file_collaborations: dict[str, list[Collaboration]],
    ) -> None:
        self._folder_collaborations = folder_collaborations
        self._file_collaborations = file_collaborations
        self.file_collaboration_calls: list[str] = []
        self.folder_collaboration_calls: list[str] = []

    def get_folder_collaborations(
        self,
        folder_id: str,
        *,
        limit: int | None = None,  # noqa: ARG002
        marker: str | None = None,  # noqa: ARG002
    ) -> Collaborations:
        self.folder_collaboration_calls.append(folder_id)
        # Box rejects collaboration queries on the root folder with HTTP 400.
        if folder_id == "0":
            raise make_box_api_error(400)
        return Collaborations(
            entries=self._folder_collaborations.get(folder_id, []),
            next_marker=None,
        )

    def get_file_collaborations(
        self,
        file_id: str,
        *,
        limit: int | None = None,  # noqa: ARG002
        marker: str | None = None,  # noqa: ARG002
    ) -> Collaborations:
        self.file_collaboration_calls.append(file_id)
        return Collaborations(
            entries=self._file_collaborations.get(file_id, []),
            next_marker=None,
        )


class FakeUsersManager:
    def __init__(
        self,
        users_by_login: dict[str, str],
        fail_status: int | None,
        page_size: int,
    ) -> None:
        # login -> user id
        self._users_by_login = users_by_login
        self._fail_status = fail_status
        self._page_size = page_size

    def get_users(
        self,
        *,
        filter_term: str | None = None,
        fields: list[str] | None = None,  # noqa: ARG002
        limit: int | None = None,  # noqa: ARG002
        usemarker: bool | None = None,  # noqa: ARG002
        marker: str | None = None,
    ) -> Users:
        if self._fail_status is not None:
            raise make_box_api_error(self._fail_status)
        # Box filter_term is a prefix match on name/login; mimic that so the
        # connector's exact-match filtering is what's under test.
        term = (filter_term or "").lower()
        matched = [
            UserFull(id=uid, login=login)
            for login, uid in self._users_by_login.items()
            if login.lower().startswith(term)
        ]
        # marker is a stringified offset; page at page_size and hand back a
        # next_marker while entries remain, so the connector's marker loop runs.
        start = int(marker) if marker else 0
        page = matched[start : start + self._page_size]
        end = start + len(page)
        next_marker = str(end) if end < len(matched) else None
        return Users(entries=page, next_marker=next_marker)


class FakeGroupsManager:
    def __init__(self, groups: list[GroupFull], page_size: int) -> None:
        self._groups = groups
        self._page_size = page_size

    def get_groups(
        self,
        *,
        filter_term: str | None = None,  # noqa: ARG002
        limit: int | None = None,  # noqa: ARG002
        offset: int | None = None,
    ) -> Groups:
        start = offset or 0
        page = self._groups[start : start + self._page_size]
        return Groups(entries=page, total_count=len(self._groups))


class FakeMembershipsManager:
    def __init__(
        self,
        members_by_group: dict[str, list[UserMini]],
        page_size: int,
        fail_status_by_group: dict[str, int],
    ) -> None:
        self._members_by_group = members_by_group
        self._page_size = page_size
        self._fail_status_by_group = fail_status_by_group

    def get_group_memberships(
        self,
        group_id: str,
        *,
        limit: int | None = None,  # noqa: ARG002
        offset: int | None = None,
    ) -> GroupMemberships:
        if group_id in self._fail_status_by_group:
            raise make_box_api_error(self._fail_status_by_group[group_id])
        members = self._members_by_group.get(group_id, [])
        start = offset or 0
        page = members[start : start + self._page_size]
        entries = [GroupMembership(user=user) for user in page]
        return GroupMemberships(entries=entries, total_count=len(members))


class FakeBoxClient:
    def __init__(
        self,
        folders_by_id: dict[str, FolderFull],
        pages: dict[tuple[str, str | None], Items],
        file_contents: dict[str, bytes] | None = None,
        folder_collaborations: dict[str, list[Collaboration]] | None = None,
        file_collaborations: dict[str, list[Collaboration]] | None = None,
        fail_listing_folder_ids: set[str] | None = None,
        users_by_login: dict[str, str] | None = None,
        users_fail_status: int | None = None,
        groups: list[GroupFull] | None = None,
        members_by_group: dict[str, list[UserMini]] | None = None,
        membership_fail_status_by_group: dict[str, int] | None = None,
        files_by_id: dict[str, FileFull] | None = None,
        file_fetch_fail_status_by_id: dict[str, int] | None = None,
        event_pages: list[Events] | None = None,
        events_fail_status: int | None = None,
        events_fail_status_by_call: dict[int, int] | None = None,
        # small page so pagination loops run without thousands of fake entries
        page_size: int = 2,
    ) -> None:
        self.folders = FakeFoldersManager(
            folders_by_id, pages, fail_listing_folder_ids or set()
        )
        self.downloads = FakeDownloadsManager(file_contents or {})
        self.files = FakeFilesManager(
            files_by_id or {}, file_fetch_fail_status_by_id or {}
        )
        self.list_collaborations = FakeListCollaborationsManager(
            folder_collaborations or {}, file_collaborations or {}
        )
        self.users = FakeUsersManager(
            users_by_login or {}, users_fail_status, page_size
        )
        self.groups = FakeGroupsManager(groups or [], page_size)
        self.memberships = FakeMembershipsManager(
            members_by_group or {}, page_size, membership_fail_status_by_group or {}
        )
        fail_status_by_call = dict(events_fail_status_by_call or {})
        if events_fail_status is not None:
            fail_status_by_call[1] = events_fail_status
        self.events = FakeEventsManager(event_pages or [], fail_status_by_call)
