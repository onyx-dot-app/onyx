"""The generated tenant: sites, libraries, folders, files, site pages, users,
groups and role assignments. The same settings always give the same corpus.

The corpus also holds the changes a test makes after generation. Each change
gets the next sequence number, which the delta API reads.
"""

import itertools
import random
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import quote, unquote

from pydantic import BaseModel, Field

from .settings import SUPPORTED_MIMES, UNSUPPORTED_MIMES, CorpusSettings

# SharePoint RoleTypeKind values.
ROLE_KINDS: dict[str, int] = {
    "limited": 1,
    "read": 2,
    "contribute": 3,
    "full_control": 5,
    "edit": 6,
}
LIMITED_ACCESS_KINDS = frozenset({1, 9})
# SharePoint PrincipalType values.
USER_TYPE = 1
ENTRA_GROUP_TYPE = 4
SITE_GROUP_TYPE = 8
ONMICROSOFT = ".onmicrosoft"
# Graph gives this URL form for Office documents.
_DOC_ASPX_EXTENSIONS = frozenset({"docx", "pptx"})
_OFFICE_DOCUMENT_URL = (
    "{site}/_layouts/15/Doc.aspx?sourcedoc=%7B{unique_id}%7D&file={name}"
    "&action=default&mobileredirect=true"
)
_TITLE_WORDS = (
    "Budget Plan Report Roadmap Review Notes Summary Policy Contract Forecast "
    "Launch Design Audit Invoice Proposal Handbook Checklist Schedule"
).split()

PrincipalKind = Literal["user", "entra_group", "site_group", "everyone"]


class CorpusError(ValueError):
    """A control request that names something the corpus does not have."""


class Principal(BaseModel):
    """Who a role assignment or a site group names. `key` is a user's object
    id, an Entra group's id or a site group's name."""

    model_config = {"frozen": True}

    kind: PrincipalKind
    key: str = ""


class RoleAssignment(BaseModel):
    principal: Principal
    role_kinds: list[int]


class SharingLink(BaseModel):
    id: str
    scope: Literal["anonymous", "organization", "users"]
    type: Literal["view", "edit"] = "view"


class MockUser(BaseModel):
    object_id: str
    sp_id: int
    display_name: str
    user_principal_name: str

    @property
    def login_name(self) -> str:
        return f"i:0#.f|membership|{self.user_principal_name}"

    @property
    def email(self) -> str:
        """The address Onyx stores: the principal name without .onmicrosoft."""
        return self.user_principal_name.replace(ONMICROSOFT, "")


class MockEntraGroup(BaseModel):
    id: str
    sp_id: int
    display_name: str
    # False for a Microsoft 365 group and for a distribution list.
    security_enabled: bool
    m365: bool = False
    member_user_ids: list[str] = Field(default_factory=list)
    member_group_ids: list[str] = Field(default_factory=list)

    @property
    def login_name(self) -> str:
        if self.m365:
            return f"c:0o.c|federateddirectoryclaimprovider|{self.id}"
        return f"c:0t.c|tenant|{self.id}"

    @property
    def sharepoint_title(self) -> str:
        return f"{self.display_name} Members" if self.m365 else self.display_name


class MockSiteGroup(BaseModel):
    name: str
    sp_id: int
    members: list[Principal] = Field(default_factory=list)


class MockItem(BaseModel):
    """A drive item: the root of a library, a folder or a file."""

    id: str
    drive_id: str
    parent_id: str | None
    name: str
    is_folder: bool
    mime_type: str | None = None
    supported: bool = False
    # The size Graph reports: the size of the text the content is made from.
    size: int = 0
    # Text a test gave for the content. None renders generated content.
    text: str | None = None
    version: int = 1
    created: datetime
    modified: datetime
    modified_by: str
    list_item_id: int
    unique_id: str
    # None means the item inherits its parent's role assignments.
    unique_assignments: list[RoleAssignment] | None = None
    sharing_links: list[SharingLink] = Field(default_factory=list)
    deleted: bool = False
    changed_seq: int = 0
    changed_at: datetime
    # The sequence number of the last permission change, 0 for none.
    sharing_changed_seq: int = 0

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def extension(self) -> str:
        return self.name.rpartition(".")[2].lower() if "." in self.name else ""


class MockDrive(BaseModel):
    id: str
    site_name: str
    # The library title Graph returns, such as "Documents".
    name: str
    # The library's URL segment, such as "Shared Documents".
    url_name: str
    list_id: str
    root_id: str
    created: datetime
    unique_assignments: list[RoleAssignment] | None = None


class MockPage(BaseModel):
    id: str
    site_name: str
    name: str
    title: str
    description: str
    created: datetime
    modified: datetime
    author: str
    list_item_id: int
    corrupt_canvas: bool = False
    unique_assignments: list[RoleAssignment] | None = None


class MockSite(BaseModel):
    name: str
    display_name: str
    site_guid: str
    web_guid: str
    web_url: str
    created: datetime
    personal: bool = False
    assignments: list[RoleAssignment] = Field(default_factory=list)
    site_groups: dict[str, MockSiteGroup] = Field(default_factory=dict)
    drive_ids: list[str] = Field(default_factory=list)
    page_ids: list[str] = Field(default_factory=list)


class EffectiveAccess(BaseModel):
    """What the connector's permission sync must give for one securable."""

    user_emails: list[str]
    group_ids: list[str]
    is_public: bool


class GrantRequest(BaseModel):
    principal: Principal
    role: Literal["limited", "read", "contribute", "edit", "full_control"] = "read"


class PermissionRequest(BaseModel):
    """Sets the role assignments of one securable. Name it with one of
    `item_id`, `page_id` and `drive_id` (the library)."""

    item_id: str | None = None
    page_id: str | None = None
    drive_id: str | None = None
    # True removes the unique assignments: the securable inherits again.
    inherit: bool = False
    # Start from the parent's assignments, as SharePoint does when it breaks
    # inheritance. False starts from none.
    copy_parent: bool = True
    grants: list[GrantRequest] = Field(default_factory=list)


class FileRequest(BaseModel):
    """A file to create. `parent_id` or `folder_path` (from the library root)
    names the folder; neither means the library root."""

    drive_id: str
    parent_id: str | None = None
    folder_path: str | None = None
    name: str
    text: str | None = None


def _guid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _item_id(rng: random.Random) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    return "01" + "".join(rng.choices(alphabet, k=32))


def _drive_id(rng: random.Random) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    return "b!" + "".join(rng.choices(alphabet, k=64))


def encode_path(path: str) -> str:
    return quote(path, safe="/")


class Corpus:
    def __init__(self, settings: CorpusSettings) -> None:
        self.settings = settings
        self.seq = 0
        self.users: dict[str, MockUser] = {}
        self.entra_groups: dict[str, MockEntraGroup] = {}
        self.sites: dict[str, MockSite] = {}
        self.drives: dict[str, MockDrive] = {}
        self.items: dict[str, MockItem] = {}
        self.pages: dict[str, MockPage] = {}
        self.children: dict[str, list[str]] = {}
        # Lower-case unique id -> item id, and (drive id, list item id) -> item id.
        self._by_unique_id: dict[str, str] = {}
        self._by_list_item: dict[tuple[str, int], str] = {}
        # Drive id -> (sequence number, item id) of each change, in order. An
        # entry is stale when the item changed again later.
        self.change_log: dict[str, list[tuple[int, str]]] = {}
        self._rng = random.Random(settings.seed)
        self._next_sp_id = 10
        self._next_list_item_id: dict[str, int] = {}
        self.tenant_id = _guid(self._rng)
        self._generate()

    # --- generation ---

    def _sp_id(self) -> int:
        self._next_sp_id += 1
        return self._next_sp_id

    def _list_item_id(self, list_key: str) -> int:
        value = self._next_list_item_id.get(list_key, 0) + 1
        self._next_list_item_id[list_key] = value
        return value

    def _times(self) -> tuple[datetime, datetime]:
        base = self.settings.base_time
        created = base - timedelta(seconds=self._rng.randint(3_600, 30 * 86_400))
        modified = created + timedelta(
            seconds=self._rng.randint(0, int((base - created).total_seconds()) - 1)
        )
        return created, modified

    def _generate(self) -> None:
        s = self.settings
        rng = self._rng
        for index in range(s.num_users):
            user = MockUser(
                object_id=_guid(rng),
                sp_id=self._sp_id(),
                display_name=f"User {index + 1}",
                user_principal_name=f"user{index + 1}@{s.email_domain}",
            )
            self.users[user.object_id] = user
        user_ids = list(self.users)

        security: list[MockEntraGroup] = []
        for index in range(s.num_security_groups):
            group = MockEntraGroup(
                id=_guid(rng),
                sp_id=self._sp_id(),
                display_name=f"Security Group {index + 1}",
                security_enabled=True,
                member_user_ids=rng.sample(user_ids, k=min(len(user_ids), 3)),
            )
            self.entra_groups[group.id] = group
            security.append(group)
        if len(security) >= 2:
            # A nested security group, and a distribution list that grants
            # nothing in SharePoint.
            security[0].member_group_ids.append(security[1].id)
            distribution_list = MockEntraGroup(
                id=_guid(rng),
                sp_id=self._sp_id(),
                display_name="Distribution List 1",
                security_enabled=False,
                member_user_ids=rng.sample(user_ids, k=min(len(user_ids), 2)),
            )
            self.entra_groups[distribution_list.id] = distribution_list
            security[0].member_group_ids.append(distribution_list.id)
        m365: list[MockEntraGroup] = []
        for index in range(s.num_m365_groups):
            group = MockEntraGroup(
                id=_guid(rng),
                sp_id=self._sp_id(),
                display_name=f"Team {index + 1}",
                security_enabled=False,
                m365=True,
                member_user_ids=rng.sample(user_ids, k=min(len(user_ids), 3)),
            )
            self.entra_groups[group.id] = group
            m365.append(group)

        for index in range(s.num_sites):
            self._generate_site(f"site{index + 1}", user_ids, security, m365)
        for index in range(s.num_personal_sites):
            name = f"user{index + 1}_{s.email_domain.replace('.', '_')}"
            self.sites[f"personal/{name}"] = MockSite(
                name=f"personal/{name}",
                display_name=f"User {index + 1}",
                site_guid=_guid(rng),
                web_guid=_guid(rng),
                web_url=f"https://{s.tenant}-my.sharepoint.com/personal/{name}",
                created=s.base_time - timedelta(days=60),
                personal=True,
            )

    def _generate_site(
        self,
        name: str,
        user_ids: list[str],
        security: list[MockEntraGroup],
        m365: list[MockEntraGroup],
    ) -> None:
        s = self.settings
        rng = self._rng
        site = MockSite(
            name=name,
            display_name=name.capitalize(),
            site_guid=_guid(rng),
            web_guid=_guid(rng),
            web_url=f"https://{s.sharepoint_host}/sites/{name}",
            created=s.base_time - timedelta(days=60),
        )
        self.sites[name] = site

        def user_members(count: int) -> list[Principal]:
            chosen = rng.sample(user_ids, k=min(len(user_ids), count))
            return [Principal(kind="user", key=user_id) for user_id in chosen]

        owners = MockSiteGroup(
            name=f"{site.display_name} Owners",
            sp_id=self._sp_id(),
            members=user_members(1),
        )
        members = MockSiteGroup(
            name=f"{site.display_name} Members",
            sp_id=self._sp_id(),
            members=user_members(3),
        )
        visitors = MockSiteGroup(
            name=f"{site.display_name} Visitors",
            sp_id=self._sp_id(),
            members=user_members(2),
        )
        if security:
            members.members.append(Principal(kind="entra_group", key=security[0].id))
        if m365:
            members.members.append(
                Principal(kind="entra_group", key=rng.choice(m365).id)
            )
        if len(security) >= 3:
            visitors.members.append(Principal(kind="entra_group", key=security[2].id))
        for group in (owners, members, visitors):
            site.site_groups[group.name] = group
        site.assignments = [
            RoleAssignment(
                principal=Principal(kind="site_group", key=owners.name),
                role_kinds=[ROLE_KINDS["full_control"]],
            ),
            RoleAssignment(
                principal=Principal(kind="site_group", key=members.name),
                role_kinds=[ROLE_KINDS["edit"]],
            ),
            RoleAssignment(
                principal=Principal(kind="site_group", key=visitors.name),
                role_kinds=[ROLE_KINDS["read"]],
            ),
        ]

        for library in range(s.libraries_per_site):
            title = "Documents" if library == 0 else f"Library {library + 1}"
            url_name = "Shared Documents" if library == 0 else title
            root_id = _item_id(rng)
            drive = MockDrive(
                id=_drive_id(rng),
                site_name=name,
                name=title,
                url_name=url_name,
                list_id=_guid(rng),
                root_id=root_id,
                created=site.created,
            )
            self.drives[drive.id] = drive
            site.drive_ids.append(drive.id)
            self._add_item(
                MockItem(
                    id=root_id,
                    drive_id=drive.id,
                    parent_id=None,
                    name="root",
                    is_folder=True,
                    created=site.created,
                    modified=site.created,
                    modified_by=user_ids[0],
                    list_item_id=0,
                    unique_id=_guid(rng),
                    changed_at=site.created,
                )
            )
            numbers = itertools.count(1)
            self._fill_folder(drive, root_id, 0, numbers)
            unsupported = list(UNSUPPORTED_MIMES)
            for index in range(s.unsupported_files_per_library):
                self._generate_file(
                    drive,
                    root_id,
                    next(numbers),
                    unsupported[index % len(unsupported)],
                    supported=False,
                )

        for index in range(s.pages_per_site):
            created, modified = self._times()
            title = "Home" if index == 0 else f"News Post {index}"
            page = MockPage(
                id=_guid(rng),
                site_name=name,
                name=f"{title}.aspx",
                title=title,
                description=f"{title} of {site.display_name}",
                created=created,
                modified=modified,
                author=rng.choice(user_ids),
                list_item_id=self._list_item_id(f"{name}:pages"),
                corrupt_canvas=index
                >= s.pages_per_site - s.corrupt_canvas_pages_per_site,
            )
            self.pages[page.id] = page
            site.page_ids.append(page.id)

        self._break_inheritance_at_random(site, user_ids, security, m365)

    def _fill_folder(
        self,
        drive: MockDrive,
        folder_id: str,
        level: int,
        numbers: "itertools.count[int]",
    ) -> None:
        """Files in the folder, then its subfolders with their content."""
        s = self.settings
        extensions = list(s.extension_weights)
        weights = [s.extension_weights[e] for e in extensions]
        for _ in range(s.files_per_folder):
            extension = self._rng.choices(extensions, weights=weights)[0]
            self._generate_file(
                drive, folder_id, next(numbers), extension, supported=True
            )
        if level >= s.folder_depth:
            return
        for index in range(s.folder_branching):
            folder = self._generate_folder(drive, folder_id, f"Folder {index + 1}")
            self._fill_folder(drive, folder.id, level + 1, numbers)

    def _generate_folder(self, drive: MockDrive, parent_id: str, name: str) -> MockItem:
        created, modified = self._times()
        return self._add_item(
            MockItem(
                id=_item_id(self._rng),
                drive_id=drive.id,
                parent_id=parent_id,
                name=name,
                is_folder=True,
                created=created,
                modified=modified,
                modified_by=self._rng.choice(list(self.users)),
                list_item_id=self._list_item_id(drive.id),
                unique_id=_guid(self._rng),
                changed_at=modified,
            )
        )

    def _generate_file(
        self,
        drive: MockDrive,
        parent_id: str,
        number: int,
        extension: str,
        supported: bool,
    ) -> MockItem:
        s = self.settings
        rng = self._rng
        created, modified = self._times()
        size = int(
            min(
                s.max_content_bytes,
                max(100, rng.lognormvariate(0, 0.6) * s.avg_content_bytes),
            )
        )
        title = " ".join(rng.sample(_TITLE_WORDS, k=2))
        mimes = SUPPORTED_MIMES if supported else UNSUPPORTED_MIMES
        return self._add_item(
            MockItem(
                id=_item_id(rng),
                drive_id=drive.id,
                parent_id=parent_id,
                name=f"{title} {number}.{extension}",
                is_folder=False,
                mime_type=mimes[extension],
                supported=supported,
                size=size,
                created=created,
                modified=modified,
                modified_by=rng.choice(list(self.users)),
                list_item_id=self._list_item_id(drive.id),
                unique_id=_guid(rng),
                changed_at=modified,
            )
        )

    def _add_item(self, item: MockItem) -> MockItem:
        self.seq += 1
        item.changed_seq = self.seq
        self.change_log.setdefault(item.drive_id, []).append((self.seq, item.id))
        self.items[item.id] = item
        self._by_unique_id[item.unique_id.lower()] = item.id
        self._by_list_item[(item.drive_id, item.list_item_id)] = item.id
        self.children.setdefault(item.id, [])
        if item.parent_id is not None:
            self.children[item.parent_id].append(item.id)
        return item

    def _break_inheritance_at_random(
        self,
        site: MockSite,
        user_ids: list[str],
        security: list[MockEntraGroup],
        m365: list[MockEntraGroup],
    ) -> None:
        s = self.settings
        rng = self._rng
        owners = site.assignments[0]
        candidates: list[Principal] = [
            Principal(kind="user", key=user_id) for user_id in user_ids
        ]
        candidates += [Principal(kind="entra_group", key=g.id) for g in security]
        candidates += [Principal(kind="entra_group", key=g.id) for g in m365]
        for drive_id in site.drive_ids:
            for item in self.drive_items(drive_id):
                if item.is_root:
                    continue
                if rng.random() < s.unique_permission_fraction:
                    grants = [
                        RoleAssignment(
                            principal=principal,
                            role_kinds=[
                                rng.choice([ROLE_KINDS["read"], ROLE_KINDS["edit"]])
                            ],
                        )
                        for principal in rng.sample(candidates, k=rng.randint(1, 2))
                    ]
                    if rng.random() < s.public_fraction:
                        grants.append(
                            RoleAssignment(
                                principal=Principal(kind="everyone"),
                                role_kinds=[ROLE_KINDS["read"]],
                            )
                        )
                    item.unique_assignments = [owners.model_copy(deep=True), *grants]
                    self._add_limited_access(site, grants)
                elif not item.is_folder and rng.random() < s.sharing_link_fraction:
                    scope = rng.choice(["anonymous", "organization", "users"])
                    self._add_sharing_link(site, item, scope, _guid(rng))

    def _add_limited_access(self, site: MockSite, grants: list[RoleAssignment]) -> None:
        """SharePoint gives Limited Access on the web to a principal that gets
        a unique grant below it."""
        assigned = {assignment.principal for assignment in site.assignments}
        for grant in grants:
            if grant.principal not in assigned:
                assigned.add(grant.principal)
                site.assignments.append(
                    RoleAssignment(
                        principal=grant.principal, role_kinds=[ROLE_KINDS["limited"]]
                    )
                )

    def _add_sharing_link(
        self, site: MockSite, item: MockItem, scope: str, link_id: str
    ) -> None:
        """A sharing link breaks inheritance and grants through a site group
        that SharePoint makes for the link."""
        kind = {"anonymous": "AnonymousView", "organization": "OrganizationView"}.get(
            scope, "Flexible"
        )
        group = MockSiteGroup(
            name=f"SharingLinks.{item.unique_id}.{kind}.{link_id}",
            sp_id=self._sp_id(),
        )
        site.site_groups[group.name] = group
        grant = RoleAssignment(
            principal=Principal(kind="site_group", key=group.name),
            role_kinds=[ROLE_KINDS["read"]],
        )
        if item.unique_assignments is None:
            item.unique_assignments = [
                a.model_copy(deep=True) for a in self.item_assignments(item)
            ]
        item.unique_assignments.append(grant)
        item.sharing_links.append(
            SharingLink.model_validate({"id": link_id, "scope": scope})
        )
        self._add_limited_access(site, [grant])

    # --- reads ---

    @property
    def sharepoint_host(self) -> str:
        return self.settings.sharepoint_host

    def site_graph_id(self, site: MockSite) -> str:
        host = site.web_url.split("/")[2]
        return f"{host},{site.site_guid},{site.web_guid}"

    def site_by_graph_id(self, graph_id: str) -> MockSite | None:
        for site in self.sites.values():
            if graph_id in (self.site_graph_id(site), site.site_guid):
                return site
        return None

    def site_by_path(self, host: str, path: str) -> MockSite | None:
        """The site at a server-relative path such as /sites/site1."""
        wanted = f"https://{host}/{path.strip('/')}".lower()
        for site in self.sites.values():
            if site.web_url.lower() == wanted:
                return site
        return None

    def site_of(self, drive: MockDrive) -> MockSite:
        return self.sites[drive.site_name]

    def drive_web_url(self, drive: MockDrive) -> str:
        return f"{self.site_of(drive).web_url}/{encode_path(drive.url_name)}"

    def drive_items(self, drive_id: str) -> list[MockItem]:
        """The live items of a drive, parents before children."""
        ordered: list[MockItem] = []
        queue: deque[str] = deque([self.drives[drive_id].root_id])
        while queue:
            item = self.items[queue.popleft()]
            ordered.append(item)
            queue.extend(self.children[item.id])
        return ordered

    def live_children(self, item_id: str) -> list[MockItem]:
        children = [self.items[child] for child in self.children[item_id]]
        return sorted(children, key=lambda child: child.name.lower())

    def path_names(self, item: MockItem) -> list[str]:
        """The names from the library root down to the item. Empty for the
        root."""
        names: list[str] = []
        current = item
        while current.parent_id is not None:
            names.append(current.name)
            current = self.items[current.parent_id]
        names.reverse()
        return names

    def item_web_url(self, item: MockItem) -> str:
        drive = self.drives[item.drive_id]
        if item.is_root:
            return self.drive_web_url(drive)
        if item.extension in _DOC_ASPX_EXTENSIONS:
            return _OFFICE_DOCUMENT_URL.format(
                site=self.site_of(drive).web_url,
                unique_id=item.unique_id.upper(),
                name=quote(item.name),
            )
        path = encode_path("/".join(self.path_names(item)))
        return f"{self.drive_web_url(drive)}/{path}"

    def page_web_url(self, page: MockPage) -> str:
        site = self.sites[page.site_name]
        return f"{site.web_url}/SitePages/{quote(page.name)}"

    def item_by_path(self, drive: MockDrive, path: str) -> MockItem | None:
        """The item at a decoded path from the library root."""
        current = self.items[drive.root_id]
        for name in [part for part in path.split("/") if part]:
            match = [
                child
                for child in self.live_children(current.id)
                if child.name.lower() == name.lower()
            ]
            if not match:
                return None
            current = match[0]
        return current

    def resolve_server_relative(
        self, site: MockSite, path: str
    ) -> MockItem | MockPage | None:
        """The folder, file or page at a decoded server-relative path, such as
        /sites/site1/Shared Documents/Folder 1."""
        site_path = "/" + site.web_url.split("/", 3)[3]
        if not path.lower().startswith(site_path.lower() + "/"):
            return None
        library, _, rest = path[len(site_path) + 1 :].partition("/")
        if library.lower() == "sitepages":
            for page_id in site.page_ids:
                if self.pages[page_id].name.lower() == rest.lower():
                    return self.pages[page_id]
            return None
        for drive_id in site.drive_ids:
            drive = self.drives[drive_id]
            if drive.url_name.lower() == library.lower():
                return self.item_by_path(drive, rest)
        return None

    def item_by_unique_id(self, site: MockSite, unique_id: str) -> MockItem | None:
        item = self.items.get(self._by_unique_id.get(unique_id.lower(), ""))
        if item is None or item.deleted or item.drive_id not in site.drive_ids:
            return None
        return item

    def item_by_list_item_id(
        self, site: MockSite, list_id: str, list_item_id: int
    ) -> MockItem | None:
        drive = self.drive_by_list_id(site, list_id)
        if drive is None:
            return None
        item = self.items.get(self._by_list_item.get((drive.id, list_item_id), ""))
        if item is None or item.deleted or item.is_root:
            return None
        return item

    def drive_by_list_id(self, site: MockSite, list_id: str) -> MockDrive | None:
        for drive_id in site.drive_ids:
            if self.drives[drive_id].list_id.lower() == list_id.lower():
                return self.drives[drive_id]
        return None

    # --- permissions ---

    def drive_assignments(self, drive: MockDrive) -> list[RoleAssignment]:
        if drive.unique_assignments is not None:
            return drive.unique_assignments
        return self.site_of(drive).assignments

    def item_assignments(self, item: MockItem) -> list[RoleAssignment]:
        """The assignments of the nearest securable with unique permissions."""
        current: MockItem | None = item
        while current is not None:
            if current.unique_assignments is not None:
                return current.unique_assignments
            current = self.items[current.parent_id] if current.parent_id else None
        return self.drive_assignments(self.drives[item.drive_id])

    def page_assignments(self, page: MockPage) -> list[RoleAssignment]:
        if page.unique_assignments is not None:
            return page.unique_assignments
        return self.sites[page.site_name].assignments

    def principal_title(self, principal: Principal) -> str:
        if principal.kind == "user":
            return self.users[principal.key].display_name
        if principal.kind == "entra_group":
            return self.entra_groups[principal.key].sharepoint_title
        if principal.kind == "site_group":
            return principal.key
        return "Everyone except external users"

    def principal_login_name(self, principal: Principal) -> str:
        if principal.kind == "user":
            return self.users[principal.key].login_name
        if principal.kind == "entra_group":
            return self.entra_groups[principal.key].login_name
        if principal.kind == "site_group":
            return principal.key
        return f"c:0-.f|rolemanager|spo-grid-all-users/{self.tenant_id}"

    def _group_name(self, site: MockSite, principal: Principal) -> str:
        """The external group name Onyx stores for a group principal."""
        if principal.kind == "site_group":
            return f"{site.web_url}::{principal.key}"
        if principal.kind == "entra_group":
            return f"{self.principal_title(principal)}_{principal.key}"
        return f"{self.principal_title(principal)}_{self.tenant_id}"

    def effective_access(
        self, site: MockSite, assignments: list[RoleAssignment]
    ) -> EffectiveAccess:
        """The access Onyx must store for a securable with these assignments.

        A user with a direct grant is listed by email. A group is listed by
        name, with each group inside it. Limited Access grants nothing, a
        distribution list inside an Entra group grants nothing, and "Everyone
        except external users" at any level makes the securable public.
        """
        emails: set[str] = set()
        names: set[str] = set()
        queue: deque[tuple[Principal, str]] = deque()
        for assignment in assignments:
            kinds = assignment.role_kinds
            if kinds and all(kind in LIMITED_ACCESS_KINDS for kind in kinds):
                continue
            principal = assignment.principal
            if principal.kind == "user":
                emails.add(self.users[principal.key].email)
            else:
                queue.append((principal, self._group_name(site, principal)))
        visited: set[Principal] = set()
        while queue:
            principal, name = queue.popleft()
            if principal.kind == "everyone":
                return EffectiveAccess(user_emails=[], group_ids=[], is_public=True)
            names.add(name.lower())
            if principal in visited:
                continue
            visited.add(principal)
            if principal.kind == "site_group":
                group = site.site_groups.get(principal.key)
                for member in group.members if group else []:
                    if member.kind != "user":
                        queue.append((member, self._group_name(site, member)))
            elif principal.kind == "entra_group":
                for nested_id in self.entra_groups[principal.key].member_group_ids:
                    nested = self.entra_groups[nested_id]
                    if nested.security_enabled:
                        queue.append(
                            (
                                Principal(kind="entra_group", key=nested_id),
                                f"{nested.display_name}_{nested_id}",
                            )
                        )
        return EffectiveAccess(
            user_emails=sorted(emails), group_ids=sorted(names), is_public=False
        )

    def expected_external_groups(self, site: MockSite) -> dict[str, list[str]]:
        """The groups, with their member emails, that Onyx's group sync must
        give for a site: each group with a grant on the web, and each group
        inside one."""
        result: dict[str, set[str]] = {}
        # (principal, login name, external group name)
        queue: deque[tuple[Principal, str, str]] = deque()
        for assignment in site.assignments:
            kinds = assignment.role_kinds
            if kinds and all(kind in LIMITED_ACCESS_KINDS for kind in kinds):
                continue
            principal = assignment.principal
            if principal.kind != "user":
                queue.append(
                    (
                        principal,
                        self.principal_login_name(principal),
                        self._group_name(site, principal),
                    )
                )
        visited: set[str] = set()
        while queue:
            principal, login_name, name = queue.popleft()
            if login_name in visited:
                continue
            visited.add(login_name)
            emails = result.setdefault(name, set())
            if principal.kind == "site_group":
                group = site.site_groups.get(principal.key)
                for member in group.members if group else []:
                    if member.kind == "user":
                        emails.add(self.users[member.key].email)
                    else:
                        queue.append(
                            (
                                member,
                                self.principal_login_name(member),
                                self._group_name(site, member),
                            )
                        )
            elif principal.kind == "entra_group":
                entra = self.entra_groups[principal.key]
                emails.update(self.users[u].email for u in entra.member_user_ids)
                for nested_id in entra.member_group_ids:
                    nested = self.entra_groups[nested_id]
                    queue.append(
                        (
                            Principal(kind="entra_group", key=nested_id),
                            nested_id,
                            f"{nested.display_name}_{nested_id}",
                        )
                    )
        return {name: sorted(emails) for name, emails in sorted(result.items())}

    # --- changes ---

    def _changed(self, item: MockItem, now: datetime) -> None:
        self.seq += 1
        item.changed_seq = self.seq
        item.changed_at = now
        self.change_log[item.drive_id].append((self.seq, item.id))

    def _live_item(self, item_id: str) -> MockItem:
        item = self.items.get(item_id)
        if item is None or item.deleted:
            raise CorpusError(f"No item {item_id}")
        return item

    def touch(
        self, count: int, file_ids: list[str] | None, rng: random.Random
    ) -> list[str]:
        """Marks files as modified now, with new content."""
        if file_ids is None:
            files = [
                item
                for item in self.items.values()
                if item.supported and not item.deleted
            ]
            chosen = rng.sample(files, k=min(count, len(files)))
        else:
            chosen = [self._live_item(file_id) for file_id in file_ids]
        now = datetime.now(timezone.utc)
        for item in chosen:
            if item.is_folder:
                raise CorpusError(f"{item.id} is a folder")
            item.modified = now
            item.version += 1
            self._changed(item, now)
        return [item.id for item in chosen]

    def modify_file(self, item_id: str, text: str | None) -> MockItem:
        item = self._live_item(item_id)
        if item.is_folder:
            raise CorpusError(f"{item_id} is a folder")
        now = datetime.now(timezone.utc)
        item.modified = now
        item.version += 1
        if text is not None:
            item.text = text
            item.size = len(text.encode())
        self._changed(item, now)
        return item

    def add_file(self, request: FileRequest) -> MockItem:
        drive = self.drives.get(request.drive_id)
        if drive is None:
            raise CorpusError(f"No drive {request.drive_id}")
        if request.parent_id is not None:
            parent = self._live_item(request.parent_id)
        else:
            found = self.item_by_path(drive, unquote(request.folder_path or ""))
            if found is None:
                raise CorpusError(f"No folder {request.folder_path}")
            parent = found
        if not parent.is_folder or parent.drive_id != drive.id:
            raise CorpusError("The parent is not a folder of the drive")
        siblings = self.live_children(parent.id)
        if any(child.name.lower() == request.name.lower() for child in siblings):
            raise CorpusError(f"{request.name} exists in the folder")
        extension = request.name.rpartition(".")[2].lower()
        supported = extension in SUPPORTED_MIMES
        mime = SUPPORTED_MIMES.get(extension) or UNSUPPORTED_MIMES.get(extension)
        now = datetime.now(timezone.utc)
        text = request.text
        return self._add_item(
            MockItem(
                id=_item_id(self._rng),
                drive_id=drive.id,
                parent_id=parent.id,
                name=request.name,
                is_folder=False,
                mime_type=mime or "application/octet-stream",
                supported=supported,
                size=len(text.encode()) if text is not None else 800,
                text=text,
                created=now,
                modified=now,
                modified_by=next(iter(self.users)),
                list_item_id=self._list_item_id(drive.id),
                unique_id=_guid(self._rng),
                changed_at=now,
            )
        )

    def delete_item(self, item_id: str) -> list[str]:
        """Deletes an item and, for a folder, the items under it. The delta
        API then lists them with a `deleted` facet."""
        item = self._live_item(item_id)
        if item.parent_id is None:
            raise CorpusError("The root of a library cannot be deleted")
        now = datetime.now(timezone.utc)
        deleted: list[str] = []
        queue: deque[MockItem] = deque([item])
        while queue:
            current = queue.popleft()
            queue.extend(self.items[child] for child in self.children[current.id])
            self.children[current.id] = []
            current.deleted = True
            self._changed(current, now)
            deleted.append(current.id)
        self.children[item.parent_id].remove(item.id)
        return deleted

    def _resolve_principal(self, site: MockSite, principal: Principal) -> Principal:
        key = principal.key
        if principal.kind == "everyone":
            return Principal(kind="everyone")
        if principal.kind == "user":
            for user in self.users.values():
                if key in (user.object_id, user.user_principal_name, user.email):
                    return Principal(kind="user", key=user.object_id)
        elif principal.kind == "entra_group":
            for group in self.entra_groups.values():
                if key in (group.id, group.display_name):
                    return Principal(kind="entra_group", key=group.id)
        elif key in site.site_groups:
            return principal
        raise CorpusError(f"No {principal.kind} '{key}'")

    def set_permissions(self, request: PermissionRequest) -> list[RoleAssignment]:
        """Breaks or restores inheritance on an item, a page or a library, and
        returns the assignments that then apply to it."""
        named = [request.item_id, request.page_id, request.drive_id]
        if sum(value is not None for value in named) != 1:
            raise CorpusError("Name one of item_id, page_id and drive_id")
        target: MockItem | MockPage | MockDrive
        if request.item_id is not None:
            target = self._live_item(request.item_id)
            if target.parent_id is None:
                raise CorpusError("Use drive_id for the root of a library")
            site = self.site_of(self.drives[target.drive_id])
        elif request.page_id is not None:
            if request.page_id not in self.pages:
                raise CorpusError(f"No page {request.page_id}")
            target = self.pages[request.page_id]
            site = self.sites[target.site_name]
        else:
            if request.drive_id not in self.drives:
                raise CorpusError(f"No drive {request.drive_id}")
            target = self.drives[request.drive_id]
            site = self.site_of(target)

        if request.inherit:
            target.unique_assignments = None
        else:
            target.unique_assignments = None
            inherited = self.assignments_of(target)
            assignments = (
                [a.model_copy(deep=True) for a in inherited]
                if request.copy_parent
                else []
            )
            grants = [
                RoleAssignment(
                    principal=self._resolve_principal(site, grant.principal),
                    role_kinds=[ROLE_KINDS[grant.role]],
                )
                for grant in request.grants
            ]
            target.unique_assignments = assignments + grants
            self._add_limited_access(site, grants)

        now = datetime.now(timezone.utc)
        if isinstance(target, MockDrive):
            target = self.items[target.root_id]
        if isinstance(target, MockItem):
            self._changed(target, now)
            target.sharing_changed_seq = self.seq
        return self.assignments_of(target)

    def assignments_of(
        self, target: MockItem | MockPage | MockDrive
    ) -> list[RoleAssignment]:
        if isinstance(target, MockItem):
            return self.item_assignments(target)
        if isinstance(target, MockPage):
            return self.page_assignments(target)
        return self.drive_assignments(target)

    # --- control views ---

    def folder_web_url(self, item: MockItem) -> str:
        """The raw id of the folder's hierarchy node."""
        drive = self.drives[item.drive_id]
        path = encode_path("/".join(self.path_names(item)))
        return f"{self.drive_web_url(drive)}/{path}"

    def summary(self, include_ids: bool) -> dict[str, Any]:
        live = [item for item in self.items.values() if not item.deleted]
        files = [item for item in live if not item.is_folder]
        folders = [item for item in live if item.is_folder and not item.is_root]
        sites = [site for site in self.sites.values() if not site.personal]
        summary: dict[str, Any] = {
            "tenant": self.settings.tenant,
            "tenant_id": self.tenant_id,
            "sharepoint_host": self.sharepoint_host,
            "sites": len(sites),
            "drives": len(self.drives),
            "folders": len(folders),
            "supported_files": sum(item.supported for item in files),
            "unsupported_files": sum(not item.supported for item in files),
            "pages": len(self.pages),
            "users": len(self.users),
            "entra_groups": len(self.entra_groups),
            "items_with_unique_permissions": sum(
                item.unique_assignments is not None for item in live
            ),
            "site_urls": [site.web_url for site in sites],
            "personal_site_urls": [
                site.web_url for site in self.sites.values() if site.personal
            ],
            "user_emails": [user.email for user in self.users.values()],
        }
        if include_ids:
            summary.update(
                {
                    "drive_ids": list(self.drives),
                    "drive_web_urls": [
                        self.drive_web_url(drive) for drive in self.drives.values()
                    ],
                    "supported_file_ids": [i.id for i in files if i.supported],
                    "unsupported_file_ids": [i.id for i in files if not i.supported],
                    "page_ids": list(self.pages),
                    "folder_ids": [item.id for item in folders],
                    "folder_web_urls": [self.folder_web_url(i) for i in folders],
                    "unique_permission_item_ids": [
                        item.id for item in live if item.unique_assignments is not None
                    ],
                    "sharing_link_item_ids": [i.id for i in live if i.sharing_links],
                }
            )
        return summary

    def describe_assignments(
        self, assignments: list[RoleAssignment]
    ) -> list[dict[str, Any]]:
        return [
            {
                "kind": assignment.principal.kind,
                "title": self.principal_title(assignment.principal),
                "login_name": self.principal_login_name(assignment.principal),
                "role_kinds": assignment.role_kinds,
            }
            for assignment in assignments
        ]
