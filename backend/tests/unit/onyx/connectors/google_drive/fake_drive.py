"""An in-memory Drive tenant for exercising the phased retrieval engine.

It replaces the listing functions the connector calls (not the raw Google
client), so tests control who sees what and how listings paginate without
emulating the Drive query language. Page tokens are scoped to the listing that
issued them; reusing one for a different principal or partition fails the test.
"""

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from onyx.connectors.google_drive import connector as connector_mod
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.drive_access import (
    DriveMember,
    DriveRole,
    PrincipalType,
)
from onyx.connectors.google_drive.models import (
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.models import ConnectorFailure, Document, HierarchyNode

DOMAIN = "co.com"
PAGE_SIZE = 2


def drive_file(
    file_id: str, owner: str | None = None, drive_id: str | None = None
) -> dict[str, Any]:
    file: dict[str, Any] = {
        "id": file_id,
        "name": file_id,
        "mimeType": "text/plain",
        "modifiedTime": "2024-06-01T00:00:00+00:00",
        "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
    }
    if owner is not None:
        file["owners"] = [{"emailAddress": owner}]
    if drive_id is not None:
        file["driveId"] = drive_id
    return file


@dataclass
class SharedDrive:
    members: list[DriveMember]
    # File ids every member sees, and file ids only an organizer sees.
    files: list[str]
    restricted_files: list[str] = field(default_factory=list)


@dataclass
class Folder:
    owner: str | None
    drive_id: str | None
    # email -> file ids that email sees when crawling the folder
    visible_files: dict[str, list[str]]
    permission_emails: list[str] | None = None


@dataclass
class FakeTenant:
    users: list[str]
    shared_drives: dict[str, SharedDrive] = field(default_factory=dict)
    # email -> files the user owns, in listing order (shortcut targets included)
    my_drive: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # email -> extra files visible to the user but owned by someone else
    shared_with: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    folders: dict[str, Folder] = field(default_factory=dict)
    groups: dict[str, list[str]] = field(default_factory=dict)
    broken_users: set[str] = field(default_factory=set)

    @property
    def admin(self) -> str:
        return self.users[0]

    # --- the functions the connector module calls ---------------------------

    def get_drive_service(self, _creds: object, email: str) -> MagicMock:
        service = MagicMock()
        service.fake_email = email
        return service

    def get_root_folder_id(self, service: MagicMock) -> str:
        if service.fake_email in self.broken_users:
            raise RefreshError("token_refresh_failed")
        return f"root-{service.fake_email}"

    def list_drive_members(
        self, _admin_service: MagicMock, drive_id: str
    ) -> list[DriveMember]:
        drive = self.shared_drives.get(drive_id)
        return list(drive.members) if drive else []

    def list_group_member_emails(
        self, _admin_service: MagicMock, group_email: str
    ) -> list[str]:
        return list(self.groups.get(group_email, []))

    def _drive_role(self, email: str, drive_id: str) -> DriveRole | None:
        drive = self.shared_drives.get(drive_id)
        if drive is None:
            return None
        for member in drive.members:
            if member.principal_type is PrincipalType.USER and member.email == email:
                return member.role
            if (
                member.principal_type is PrincipalType.GROUP
                and email in self.groups.get(member.email or "", [])
            ):
                return member.role
        return None

    def can_list_drive(self, service: MagicMock, drive_id: str) -> bool:
        email = service.fake_email
        if email in self.broken_users:
            return False
        return self._drive_role(email, drive_id) is not None

    def get_files_in_shared_drive(
        self,
        service: MagicMock,
        drive_id: str,
        max_num_pages: int,
        page_token: str | None = None,
        **_kwargs: object,
    ) -> Iterator[dict[str, Any] | str]:
        email = service.fake_email
        if email in self.broken_users:
            raise RefreshError("token_refresh_failed")
        role = self._drive_role(email, drive_id)
        if role is None:
            return
        drive = self.shared_drives[drive_id]
        ids = list(drive.files)
        if role is DriveRole.ORGANIZER:
            ids += drive.restricted_files
        files = [drive_file(file_id, drive_id=drive_id) for file_id in ids]
        yield from _paged(files, f"drive:{drive_id}:{email}", max_num_pages, page_token)

    def get_all_files_in_my_drive_and_shared(
        self,
        service: MagicMock,
        include_shared_with_me: bool,
        max_num_pages: int,
        page_token: str | None = None,
        **_kwargs: object,
    ) -> Iterator[dict[str, Any] | str]:
        email = service.fake_email
        if email in self.broken_users:
            raise RefreshError("token_refresh_failed")
        files = list(self.my_drive.get(email, []))
        if include_shared_with_me:
            files += self.shared_with.get(email, [])
        scope = f"user:{email}:{include_shared_with_me}"
        yield from _paged(files, scope, max_num_pages, page_token)

    def probe_target(self, service: MagicMock, target_id: str) -> dict[str, Any] | None:
        folder = self.folders.get(target_id)
        if folder is None or service.fake_email not in folder.visible_files:
            return None
        return drive_file(target_id, owner=folder.owner, drive_id=folder.drive_id)

    def internal_principals_of(
        self,
        _service: MagicMock,
        target_id: str,
        google_domain: str,
        _expand_group: object,
    ) -> list[str] | None:
        folder = self.folders[target_id]
        if folder.permission_emails is None:
            return None
        return sorted(
            email
            for email in folder.permission_emails
            if email.endswith(f"@{google_domain}")
        )

    def crawl_folders_for_files(
        self,
        service: MagicMock,
        parent_id: str,
        user_email: str,
        **_kwargs: object,
    ) -> Iterator[RetrievedDriveFile]:
        folder = self.folders[parent_id]
        if service.fake_email in self.broken_users:
            raise RefreshError("token_refresh_failed")
        for file_id in folder.visible_files.get(service.fake_email, []):
            yield RetrievedDriveFile(
                completion_stage=DriveRetrievalStage.FOLDER_FILES,
                drive_file=drive_file(file_id, owner=folder.owner),
                user_email=user_email,
                parent_id=parent_id,
            )

    def patch(self, connector: GoogleDriveConnector) -> ExitStack:
        """Point the connector module at this tenant."""
        stack = ExitStack()
        fakes: dict[str, object] = {
            "get_drive_service": self.get_drive_service,
            "get_root_folder_id": self.get_root_folder_id,
            "list_drive_members": self.list_drive_members,
            "list_group_member_emails": self.list_group_member_emails,
            "can_list_drive": self.can_list_drive,
            "get_files_in_shared_drive": self.get_files_in_shared_drive,
            "get_all_files_in_my_drive_and_shared": (
                self.get_all_files_in_my_drive_and_shared
            ),
            "probe_target": self.probe_target,
            "internal_principals_of": self.internal_principals_of,
            "crawl_folders_for_files": self.crawl_folders_for_files,
        }
        for name, fake in fakes.items():
            stack.enter_context(patch.object(connector_mod, name, fake))
        stack.enter_context(
            patch.object(connector_mod, "get_admin_service", return_value=MagicMock())
        )
        stack.enter_context(
            patch.object(connector_mod, "retry_builder", return_value=lambda f: f)
        )
        stack.enter_context(
            patch.object(
                connector, "_get_all_user_emails", return_value=list(self.users)
            )
        )
        stack.enter_context(
            patch.object(
                connector,
                "get_all_drive_ids",
                return_value=set(self.shared_drives),
            )
        )
        # Conversion downloads content; the engine under test ends at retrieval.
        stack.enter_context(
            patch.object(
                connector,
                "_convert_retrieved_files_to_documents",
                side_effect=lambda files, _checkpoint, _perms: iter(files),
            )
        )
        return stack


def _paged(
    files: list[dict[str, Any]],
    scope: str,
    max_num_pages: int,
    page_token: str | None,
) -> Iterator[dict[str, Any] | str]:
    offset = 0
    if page_token is not None:
        token_scope, _, raw_offset = page_token.rpartition("@")
        if token_scope != scope:
            raise AssertionError(
                f"page token from {token_scope!r} reused for {scope!r}"
            )
        offset = int(raw_offset)
    pages = 0
    while offset < len(files):
        if pages >= max_num_pages:
            yield f"{scope}@{offset}"
            return
        yield from files[offset : offset + PAGE_SIZE]
        offset += PAGE_SIZE
        pages += 1


def make_service_account_connector(**config: Any) -> GoogleDriveConnector:
    connector = GoogleDriveConnector(**config)
    connector._creds = MagicMock(spec=ServiceAccountCredentials)
    connector._primary_admin_email = f"admin@{DOMAIN}"
    if not connector.specific_requests_made:
        connector.include_files_shared_with_me = True
    return connector


@dataclass
class RunResult:
    file_ids: list[str]
    errors: list[RetrievedDriveFile]
    checkpoints: list[GoogleDriveCheckpoint]


def run_one_call(
    connector: GoogleDriveConnector, checkpoint: GoogleDriveCheckpoint
) -> tuple[list[RetrievedDriveFile], GoogleDriveCheckpoint]:
    """One load_from_checkpoint call, as docfetching runs it."""
    output = connector.load_from_checkpoint(0, 2_000_000_000, checkpoint)
    items: list[RetrievedDriveFile] = []
    while True:
        try:
            item: Document | ConnectorFailure | HierarchyNode | RetrievedDriveFile = (
                next(output)
            )
        except StopIteration as stop:
            return items, stop.value
        if not isinstance(item, RetrievedDriveFile):
            raise AssertionError(f"unexpected item {item!r}")
        items.append(item)


def run_to_completion(
    connector: GoogleDriveConnector,
    checkpoint: GoogleDriveCheckpoint | None = None,
    max_calls: int = 500,
) -> RunResult:
    """Drive the connector call by call, persisting the checkpoint as JSON
    between calls exactly as docfetching does."""
    result = RunResult(file_ids=[], errors=[], checkpoints=[])
    checkpoint = checkpoint or connector.build_dummy_checkpoint()
    for _ in range(max_calls):
        items, checkpoint = run_one_call(connector, checkpoint)
        for item in items:
            if item.error is not None:
                result.errors.append(item)
            else:
                result.file_ids.append(item.drive_file["id"])
        checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        result.checkpoints.append(checkpoint)
        if not checkpoint.has_more:
            return result
    raise AssertionError("connector did not finish")
