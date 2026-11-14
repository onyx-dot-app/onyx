"""A generated Google Workspace: users, groups, shared drives, folders and files.

The same CorpusSettings always give the same corpus. File content is not stored;
`content.py` renders it from the file id when a client asks for it.
"""

import base64
import hashlib
import math
import random
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from .settings import (
    DOCX_MIME,
    FOLDER_MIME,
    GOOGLE_NATIVE_MIMES,
    MARKDOWN_MIME,
    PDF_MIME,
    PPTX_MIME,
    SHORTCUT_MIME,
    TEXT_MIME,
    BulkUploadSettings,
    CorpusSettings,
    FolderTreeSettings,
)

PermissionType = Literal["user", "group", "domain", "anyone"]
Role = Literal["owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"]

_CORPUS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_CORPUS_SPAN = timedelta(days=700)
_MAX_EDIT_SPAN = timedelta(days=30)
_EXTENSIONS = {
    PDF_MIME: ".pdf",
    DOCX_MIME: ".docx",
    PPTX_MIME: ".pptx",
    TEXT_MIME: ".txt",
    MARKDOWN_MIME: ".md",
}
_NAME_WORDS = (
    "quarterly roadmap budget review launch onboarding policy design notes "
    "customer research pricing hiring security incident retro planning metrics "
    "contract partner architecture release migration forecast survey handbook "
    "proposal summary audit training strategy checklist"
).split()


class MockPermission(BaseModel):
    id: str
    type: PermissionType
    role: Role
    email_address: str | None = None
    domain: str | None = None
    allow_file_discovery: bool | None = None


class MockUser(BaseModel):
    id: str
    email: str
    given_name: str
    family_name: str
    is_admin: bool
    root_folder_id: str
    permission_id: str

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}"


class MockGroup(BaseModel):
    id: str
    email: str
    name: str
    member_emails: list[str]


class MockDrive(BaseModel):
    id: str
    name: str
    created_time: datetime
    # Users and groups, with role organizer, writer or reader.
    members: list[MockPermission]


class MockFile(BaseModel):
    id: str
    name: str
    mime_type: str
    parents: list[str]
    drive_id: str | None
    # Only My Drive items have an owner.
    owner: str | None
    created_time: datetime
    modified_time: datetime
    # Permissions set on the item itself. A My Drive item lists its owner here;
    # a shared drive item inherits the drive's members on top of these.
    permissions: list[MockPermission]
    content_bytes: int
    shortcut_target_id: str | None = None
    # A My Drive root or a shared drive root.
    is_root: bool = False

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    @property
    def is_content(self) -> bool:
        """A file an indexer turns into a document."""
        return not self.is_root and self.mime_type not in (FOLDER_MIME, SHORTCUT_MIME)


def stable_digits(value: str, length: int = 20) -> str:
    digest = hashlib.sha256(value.encode()).digest()
    return str(int.from_bytes(digest[:12], "big")).rjust(length, "1")[:length]


def _whole_ms(value: datetime) -> datetime:
    """Drive keeps times to the millisecond. A finer time would compare
    differently from the time that the API returns."""
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def _make_id(prefix: str, seed: int, kind: str, n: int, length: int) -> str:
    digest = hashlib.sha256(f"{seed}:{kind}:{n}".encode()).digest()
    text = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return prefix + text.replace("-", "x").replace("_", "y")[:length]


class Corpus:
    def __init__(self, settings: CorpusSettings) -> None:
        self.settings = settings
        self.domain = settings.domain
        self.users: dict[str, MockUser] = {}
        self.groups: dict[str, MockGroup] = {}
        self.groups_of_user: dict[str, set[str]] = {}
        self.drives: dict[str, MockDrive] = {}
        self.drive_member_emails: dict[str, set[str]] = {}
        # Accounts outside the domain that own files shared into it. They are
        # not users: the directory does not list them and the token endpoint
        # does not impersonate them.
        self.external_users: dict[str, MockUser] = {}
        self.external_recipients: list[str] = []
        self.folder_tree_root_ids: list[str] = []
        self.files: dict[str, MockFile] = {}
        self.children: dict[str, list[str]] = {}
        self.drive_files: dict[str, list[str]] = {}
        # Items in a user's My Drive or shared with the user or the user's groups:
        # the "user" corpus of files.list.
        self.user_corpus: dict[str, set[str]] = {}
        self._rng = random.Random(settings.seed)
        self._file_count = 0
        self._generate()

    @property
    def admin_email(self) -> str:
        return f"admin@{self.domain}"

    def content_files(self) -> Iterator[MockFile]:
        return (f for f in self.files.values() if f.is_content)

    def account(self, email: str) -> MockUser | None:
        """A domain user or an external account."""
        return self.users.get(email) or self.external_users.get(email)

    def principals_of(self, email: str) -> set[str]:
        return {email} | self.groups_of_user.get(email, set())

    def is_drive_member(self, email: str, drive_id: str) -> bool:
        return email in self.drive_member_emails.get(drive_id, set())

    def member_drive_ids(self, email: str) -> list[str]:
        return [d for d in self.drives if self.is_drive_member(email, d)]

    def root_of(self, email: str) -> MockFile | None:
        user = self.users.get(email)
        return self.files.get(user.root_folder_id) if user else None

    def has_direct_role(self, email: str, file: MockFile, roles: set[str]) -> bool:
        principals = self.principals_of(email)
        return any(
            p.role in roles and p.email_address in principals for p in file.permissions
        )

    def can_read(self, email: str, file: MockFile) -> bool:
        if file.is_root:
            if file.drive_id is not None:
                return self.is_drive_member(email, file.drive_id)
            return file.owner == email
        if file.owner == email:
            return True
        if file.drive_id is not None and self.is_drive_member(email, file.drive_id):
            return True
        principals = self.principals_of(email)
        user_domain = email.split("@")[-1]
        for permission in file.permissions:
            if permission.type in ("user", "group"):
                if permission.email_address in principals:
                    return True
            elif permission.type == "domain":
                if permission.domain == user_domain:
                    return True
            elif permission.type == "anyone":
                return True
        return False

    def can_share(self, email: str, file: MockFile) -> bool:
        if file.drive_id is not None:
            return False
        return file.owner == email or self.has_direct_role(email, file, {"writer"})

    def all_drives_content_ids(self, email: str) -> list[str]:
        """Content files in the user corpus or a member shared drive."""
        mine = self.user_corpus.get(email, set())
        drives = set(self.member_drive_ids(email))
        return [
            f.id for f in self.content_files() if f.id in mine or f.drive_id in drives
        ]

    def subtree_content_ids(self, folder_id: str) -> list[str]:
        """The content files under a folder, at any depth, once each. A
        shortcut counts as its target, as a folder target follows it."""
        found: list[str] = []
        pending = [folder_id]
        seen = {folder_id}
        while pending:
            for child_id in self.children.get(pending.pop(), []):
                child = self.files[child_id]
                if child.shortcut_target_id is not None:
                    child = self.files[child.shortcut_target_id]
                if child.is_content and child.id not in seen:
                    seen.add(child.id)
                    found.append(child.id)
                elif child.is_folder and child.id not in seen:
                    seen.add(child.id)
                    pending.append(child.id)
        return found

    def touch(self, count: int, rng: random.Random) -> list[str]:
        """Marks `count` random content files as modified now."""
        candidates = [f.id for f in self.content_files()]
        chosen = rng.sample(candidates, min(count, len(candidates)))
        now = _whole_ms(datetime.now(timezone.utc))
        for file_id in chosen:
            self.files[file_id].modified_time = now
        return chosen

    # -- generation ---------------------------------------------------------

    def _generate(self) -> None:
        s = self.settings
        rng = self._rng
        for i in range(s.num_users):
            local = "admin" if i == 0 else f"user{i}"
            email = f"{local}@{self.domain}"
            root_id = _make_id("0A", s.seed, "root", i, 17)
            self.users[email] = MockUser(
                id=stable_digits(f"user:{email}", 21),
                email=email,
                given_name=local.capitalize(),
                family_name="Mock",
                is_admin=i == 0,
                root_folder_id=root_id,
                permission_id=stable_digits(email),
            )
            self.groups_of_user[email] = set()
            self.user_corpus[email] = set()
            self._add(
                MockFile(
                    id=root_id,
                    name="My Drive",
                    mime_type=FOLDER_MIME,
                    parents=[],
                    drive_id=None,
                    owner=email,
                    created_time=_CORPUS_START,
                    modified_time=_CORPUS_START,
                    permissions=[self._user_permission(email, "owner")],
                    content_bytes=0,
                    is_root=True,
                )
            )

        user_emails = list(self.users)
        non_admins = user_emails[1:] or user_emails
        for j in range(s.num_groups):
            email = f"group{j + 1}@{self.domain}"
            members = rng.sample(non_admins, min(len(non_admins), rng.randint(2, 4)))
            self.groups[email] = MockGroup(
                id=_make_id("0", s.seed, "group", j, 14),
                email=email,
                name=f"Group {j + 1}",
                member_emails=members,
            )
            for member in members:
                self.groups_of_user[member].add(email)

        for k in range(s.num_shared_drives):
            self._generate_drive(k, non_admins)

        for email in user_emails:
            user = self.users[email]
            self._populate_container(
                root_id=user.root_folder_id,
                drive_id=None,
                owner=email,
                num_files=s.files_per_user,
            )

        self._generate_shortcuts()
        # A separate random stream, so these settings do not change the rest.
        extra_rng = random.Random(f"{s.seed}:extra")
        self._generate_external_shares(extra_rng)
        for bulk in s.bulk_uploads:
            self._generate_bulk_upload(bulk, extra_rng)
        for tree in s.folder_trees:
            self._generate_folder_tree(tree, extra_rng)
        self._index_user_corpus()

    def _generate_drive(self, k: int, non_admins: list[str]) -> None:
        s = self.settings
        rng = self._rng
        drive_id = _make_id("0A", s.seed, "drive", k, 17)
        members: list[MockPermission] = []
        for email in rng.sample(non_admins, min(len(non_admins), rng.randint(1, 3))):
            role: Role = rng.choice(["organizer", "writer", "reader"])
            members.append(self._user_permission(email, role))
        if self.groups and rng.random() < 0.5:
            group = rng.choice(list(self.groups.values()))
            members.append(self._group_permission(group.email, "reader"))
        if rng.random() < s.admin_drive_membership or not members:
            members.append(self._user_permission(self.admin_email, "organizer"))
        created = _CORPUS_START + _CORPUS_SPAN * rng.random() / 4
        self.drives[drive_id] = MockDrive(
            id=drive_id,
            name=f"{rng.choice(_NAME_WORDS).capitalize()} Shared Drive {k + 1}",
            created_time=created,
            members=members,
        )
        member_emails: set[str] = set()
        for member in members:
            if member.type == "user" and member.email_address:
                member_emails.add(member.email_address)
            elif member.type == "group" and member.email_address:
                member_emails.update(self.groups[member.email_address].member_emails)
        self.drive_member_emails[drive_id] = member_emails
        self.drive_files[drive_id] = []
        self._add(
            MockFile(
                id=drive_id,
                name="Drive",
                mime_type=FOLDER_MIME,
                parents=[],
                drive_id=drive_id,
                owner=None,
                created_time=created,
                modified_time=created,
                permissions=[],
                content_bytes=0,
                is_root=True,
            )
        )
        self._populate_container(
            root_id=drive_id,
            drive_id=drive_id,
            owner=None,
            num_files=s.files_per_shared_drive,
        )

    def _populate_container(
        self, *, root_id: str, drive_id: str | None, owner: str | None, num_files: int
    ) -> None:
        s = self.settings
        rng = self._rng
        depth = {root_id: 0}
        folder_ids: list[str] = []
        for _ in range(s.folders_per_container):
            candidates = [root_id] + [
                f for f in folder_ids if depth[f] < s.max_folder_depth
            ]
            parent = rng.choice(candidates)
            created, modified = self._times()
            folder = MockFile(
                id=self._next_file_id(),
                name=f"{rng.choice(_NAME_WORDS).capitalize()} {len(folder_ids) + 1}",
                mime_type=FOLDER_MIME,
                parents=[parent],
                drive_id=drive_id,
                owner=owner,
                created_time=created,
                modified_time=modified,
                permissions=self._owner_permissions(owner),
                content_bytes=0,
            )
            self._add(folder)
            depth[folder.id] = depth[parent] + 1
            folder_ids.append(folder.id)

        mimes = list(s.mime_weights)
        weights = [s.mime_weights[m] for m in mimes]
        parents = [root_id] + folder_ids
        for n in range(num_files):
            mime = rng.choices(mimes, weights)[0]
            created, modified = self._times()
            words = " ".join(w.capitalize() for w in rng.sample(_NAME_WORDS, 2))
            permissions = self._owner_permissions(owner)
            if owner is not None and rng.random() < s.share_fraction:
                permissions.extend(self._random_shares(owner))
            elif drive_id is not None and rng.random() < s.share_fraction / 4:
                outsiders = [
                    e for e in self.users if not self.is_drive_member(e, drive_id)
                ]
                if outsiders:
                    permissions.append(
                        self._user_permission(rng.choice(outsiders), "reader")
                    )
            self._add(
                MockFile(
                    id=self._next_file_id(),
                    name=f"{words} {n + 1}{_EXTENSIONS.get(mime, '')}",
                    mime_type=mime,
                    parents=[rng.choice(parents)],
                    drive_id=drive_id,
                    owner=owner,
                    created_time=created,
                    modified_time=modified,
                    permissions=permissions,
                    content_bytes=self._content_size(),
                )
            )

    def _generate_shortcuts(self) -> None:
        rng = self._rng
        targets = list(self.content_files())
        count = round(self.settings.shortcut_fraction * len(targets))
        # (parent id, shared drive id, owner) of each place a shortcut can live.
        containers: list[tuple[str, str | None, str | None]] = [
            (u.root_folder_id, None, u.email) for u in self.users.values()
        ]
        containers += [(d, d, None) for d in self.drives]
        for _ in range(count):
            target = rng.choice(targets)
            root_id, drive_id, owner = rng.choice(containers)
            created, modified = self._times()
            self._add(
                MockFile(
                    id=self._next_file_id(),
                    name=f"Shortcut to {target.name}",
                    mime_type=SHORTCUT_MIME,
                    parents=[root_id],
                    drive_id=drive_id,
                    owner=owner,
                    created_time=created,
                    modified_time=modified,
                    permissions=self._owner_permissions(owner),
                    content_bytes=0,
                    shortcut_target_id=target.id,
                )
            )

    def _generate_external_shares(self, rng: random.Random) -> None:
        external = self.settings.external_shares
        if external is None:
            return
        non_admins = list(self.users)[1:] or list(self.users)
        self.external_recipients = non_admins[: external.recipients]
        for i in range(external.owners):
            email = f"ext{i + 1}@{external.owner_domain}"
            root_id = _make_id("0A", self.settings.seed, "external-root", i, 17)
            self.external_users[email] = MockUser(
                id=stable_digits(f"user:{email}", 21),
                email=email,
                given_name=f"External{i + 1}",
                family_name="Owner",
                is_admin=False,
                root_folder_id=root_id,
                permission_id=stable_digits(email),
            )
            self._add(
                MockFile(
                    id=root_id,
                    name="My Drive",
                    mime_type=FOLDER_MIME,
                    parents=[],
                    drive_id=None,
                    owner=email,
                    created_time=_CORPUS_START,
                    modified_time=_CORPUS_START,
                    permissions=[self._user_permission(email, "owner")],
                    content_bytes=0,
                    is_root=True,
                )
            )
        owners = list(self.external_users)
        for n in range(external.files):
            created, modified = self._times(rng)
            self._add_content_file(
                rng,
                n,
                parent=self.external_users[owners[n % len(owners)]].root_folder_id,
                drive_id=None,
                owner=owners[n % len(owners)],
                created=created,
                modified=modified,
            )

    def _external_share_permissions(self) -> list[MockPermission]:
        return [self._user_permission(e, "reader") for e in self.external_recipients]

    def _container(self, kind: str, index: int) -> tuple[str, str | None, str | None]:
        """(root folder id, shared drive id, owner) of a container."""
        if kind == "shared_drive":
            drive_id = list(self.drives)[index]
            return drive_id, drive_id, None
        if kind == "external":
            account = list(self.external_users.values())[index]
            return account.root_folder_id, None, account.email
        user = list(self.users.values())[index]
        return user.root_folder_id, None, user.email

    def _generate_bulk_upload(
        self, bulk: BulkUploadSettings, rng: random.Random
    ) -> None:
        root_id, drive_id, owner = self._container(bulk.container, bulk.index)
        start = bulk.start.replace(microsecond=0)
        for burst in range(bulk.bursts):
            # Google stores a bulk upload's modifiedTime in whole seconds.
            at = start + timedelta(seconds=burst * bulk.spacing_seconds)
            for n in range(bulk.count):
                self._add_content_file(
                    rng,
                    n,
                    parent=root_id,
                    drive_id=drive_id,
                    owner=owner,
                    created=at,
                    modified=at,
                )

    def _generate_folder_tree(
        self, tree: FolderTreeSettings, rng: random.Random
    ) -> None:
        container_root, drive_id, owner = self._container(tree.container, tree.index)
        tree_root = self._add_folder(
            rng,
            f"Folder Tree {len(self.folder_tree_root_ids) + 1}",
            container_root,
            drive_id,
            owner,
        )
        self.folder_tree_root_ids.append(tree_root)
        level = [tree_root]
        for depth in range(tree.depth + 1):
            for folder_id in level:
                for n in range(tree.files_per_folder):
                    self._add_tree_file(rng, n, folder_id, drive_id, owner)
            if depth == tree.depth:
                break
            level = [
                self._add_folder(
                    rng, f"Level {depth + 1}.{b + 1}", parent, drive_id, owner
                )
                for parent in level
                for b in range(tree.branching)
            ]
        for n in range(tree.deepest_folder_files):
            self._add_tree_file(
                rng, tree.files_per_folder + n, level[0], drive_id, owner
            )
        if tree.cycle_shortcut:
            self._add_folder_shortcut(rng, level[0], tree_root, drive_id, owner)
        if tree.shortcut_to_tree is not None:
            self._add_folder_shortcut(
                rng,
                tree_root,
                self.folder_tree_root_ids[tree.shortcut_to_tree],
                drive_id,
                owner,
            )

    def _add_folder_shortcut(
        self,
        rng: random.Random,
        parent: str,
        target_id: str,
        drive_id: str | None,
        owner: str | None,
    ) -> None:
        created, modified = self._times(rng)
        self._add(
            MockFile(
                id=self._next_file_id(),
                name=f"Shortcut to {self.files[target_id].name}",
                mime_type=SHORTCUT_MIME,
                parents=[parent],
                drive_id=drive_id,
                owner=owner,
                created_time=created,
                modified_time=modified,
                permissions=self._owner_permissions(owner),
                content_bytes=0,
                shortcut_target_id=target_id,
            )
        )

    def _add_tree_file(
        self,
        rng: random.Random,
        n: int,
        parent: str,
        drive_id: str | None,
        owner: str | None,
    ) -> None:
        created, modified = self._times(rng)
        self._add_content_file(
            rng,
            n,
            parent=parent,
            drive_id=drive_id,
            owner=owner,
            created=created,
            modified=modified,
        )

    def _add_folder(
        self,
        rng: random.Random,
        name: str,
        parent: str,
        drive_id: str | None,
        owner: str | None,
    ) -> str:
        created, modified = self._times(rng)
        folder = MockFile(
            id=self._next_file_id(),
            name=name,
            mime_type=FOLDER_MIME,
            parents=[parent],
            drive_id=drive_id,
            owner=owner,
            created_time=created,
            modified_time=modified,
            permissions=self._owner_permissions(owner),
            content_bytes=0,
        )
        self._add(folder)
        return folder.id

    def _add_content_file(
        self,
        rng: random.Random,
        n: int,
        *,
        parent: str,
        drive_id: str | None,
        owner: str | None,
        created: datetime,
        modified: datetime,
    ) -> None:
        s = self.settings
        mimes = list(s.mime_weights)
        mime = rng.choices(mimes, [s.mime_weights[m] for m in mimes])[0]
        words = " ".join(w.capitalize() for w in rng.sample(_NAME_WORDS, 2))
        permissions = self._owner_permissions(owner)
        if owner in self.external_users:
            permissions.extend(self._external_share_permissions())
        self._add(
            MockFile(
                id=self._next_file_id(),
                name=f"{words} {n + 1}{_EXTENSIONS.get(mime, '')}",
                mime_type=mime,
                parents=[parent],
                drive_id=drive_id,
                owner=owner,
                created_time=created,
                modified_time=modified,
                permissions=permissions,
                content_bytes=self._content_size(rng),
            )
        )

    def _index_user_corpus(self) -> None:
        for file in self.files.values():
            if file.is_root:
                continue
            if file.owner in self.user_corpus:
                self.user_corpus[file.owner].add(file.id)
            for permission in file.permissions:
                if (
                    permission.type == "user"
                    and permission.email_address in self.user_corpus
                ):
                    self.user_corpus[permission.email_address].add(file.id)
                elif permission.type == "group" and permission.email_address:
                    group = self.groups[permission.email_address]
                    for member in group.member_emails:
                        self.user_corpus[member].add(file.id)

    def _add(self, file: MockFile) -> None:
        self.files[file.id] = file
        for parent in file.parents:
            self.children.setdefault(parent, []).append(file.id)
        if file.drive_id is not None and not file.is_root:
            self.drive_files[file.drive_id].append(file.id)

    def _next_file_id(self) -> str:
        self._file_count += 1
        return _make_id("1", self.settings.seed, "file", self._file_count, 32)

    def _times(self, rng: random.Random | None = None) -> tuple[datetime, datetime]:
        rng = rng or self._rng
        created = _whole_ms(_CORPUS_START + _CORPUS_SPAN * rng.random())
        modified = _whole_ms(created + _MAX_EDIT_SPAN * rng.random())
        return created, modified

    def _content_size(self, rng: random.Random | None = None) -> int:
        sigma = 0.8
        mu = math.log(self.settings.avg_content_bytes) - sigma * sigma / 2
        size = int((rng or self._rng).lognormvariate(mu, sigma))
        return max(200, min(size, self.settings.max_content_bytes))

    def _owner_permissions(self, owner: str | None) -> list[MockPermission]:
        return [self._user_permission(owner, "owner")] if owner else []

    def _random_shares(self, owner: str) -> list[MockPermission]:
        rng = self._rng
        shares: list[MockPermission] = []
        others = [e for e in self.users if e != owner]
        for _ in range(rng.choice([1, 1, 2])):
            roll = rng.random()
            if roll < 0.65 and others:
                role: Role = rng.choice(["reader", "reader", "writer", "commenter"])
                shares.append(self._user_permission(rng.choice(others), role))
            elif roll < 0.85 and self.groups:
                group = rng.choice(list(self.groups))
                shares.append(self._group_permission(group, "reader"))
            elif roll < 0.95:
                shares.append(
                    MockPermission(
                        id=f"{stable_digits('domain:' + self.domain)}k",
                        type="domain",
                        role="reader",
                        domain=self.domain,
                        allow_file_discovery=rng.random() < 0.5,
                    )
                )
            else:
                shares.append(
                    MockPermission(
                        id="anyoneWithLink",
                        type="anyone",
                        role="reader",
                        allow_file_discovery=False,
                    )
                )
        unique: dict[str, MockPermission] = {p.id: p for p in shares}
        return list(unique.values())

    @staticmethod
    def _user_permission(email: str, role: Role) -> MockPermission:
        return MockPermission(
            id=stable_digits(email), type="user", role=role, email_address=email
        )

    @staticmethod
    def _group_permission(email: str, role: Role) -> MockPermission:
        return MockPermission(
            id=stable_digits(email), type="group", role=role, email_address=email
        )

    def summary(self) -> dict[str, object]:
        by_mime: dict[str, int] = {}
        for file in self.content_files():
            by_mime[file.mime_type] = by_mime.get(file.mime_type, 0) + 1
        return {
            "domain": self.domain,
            "admin_email": self.admin_email,
            "users": len(self.users),
            "groups": len(self.groups),
            "shared_drives": len(self.drives),
            "folders": sum(
                1 for f in self.files.values() if f.is_folder and not f.is_root
            ),
            "shortcuts": sum(
                1 for f in self.files.values() if f.mime_type == SHORTCUT_MIME
            ),
            "content_files": sum(by_mime.values()),
            "content_files_by_mime": by_mime,
            "google_native_files": sum(
                n for m, n in by_mime.items() if m in GOOGLE_NATIVE_MIMES
            ),
            "external_owner_emails": list(self.external_users),
            "external_recipient_emails": self.external_recipients,
            "folder_tree_root_ids": self.folder_tree_root_ids,
        }
