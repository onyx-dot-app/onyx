"""Plain data that the GitHub gateway returns.

The models parse the JSON of the GitHub REST API. They hold no SDK objects,
so reading a field never makes a network call.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

_ORGANIZATION_OWNER_TYPE = "Organization"

ItemT = TypeVar("ItemT")


class SerializedRepository(BaseModel):
    """The repository a checkpoint is working on."""

    # id is part of the raw_data as well, just pulled out for convenience
    id: int
    # Checkpoints written before the gateway carry the response headers.
    headers: dict[str, str | int] = Field(default_factory=dict)
    raw_data: dict[str, Any]


class GitHubOrganizationRef(BaseModel):
    id: int
    login: str


class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    html_url: str
    default_branch: str | None = None
    pushed_at: datetime | None = None
    # "public", "private" or "internal". None when the response has no value.
    visibility: str | None = None
    private: bool = False
    owner_login: str | None = None
    # The organization that owns the repository. None for a user's repository.
    organization: GitHubOrganizationRef | None = None
    raw_data: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "GitHubRepository":
        owner: Any = raw.get("owner")
        organization: Any = raw.get("organization")
        # Repository listings leave out ``organization``; an organization
        # owner is the same account.
        if not isinstance(organization, dict) and (
            isinstance(owner, dict) and owner.get("type") == _ORGANIZATION_OWNER_TYPE
        ):
            organization = owner
        return cls(
            id=raw["id"],
            name=raw["name"],
            full_name=raw["full_name"],
            html_url=raw["html_url"],
            default_branch=raw.get("default_branch"),
            pushed_at=raw.get("pushed_at"),
            visibility=raw.get("visibility"),
            private=bool(raw.get("private")),
            owner_login=owner.get("login") if isinstance(owner, dict) else None,
            organization=(
                GitHubOrganizationRef(
                    id=organization["id"], login=organization["login"]
                )
                if isinstance(organization, dict)
                else None
            ),
            raw_data=raw,
        )


def _login(user: Any) -> str | None:
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    return None


def _logins(users: Any) -> list[str]:
    if not isinstance(users, list):
        return []
    return [login for user in users if (login := _login(user))]


def _label_names(labels: Any) -> list[str]:
    if not isinstance(labels, list):
        return []
    return [
        label["name"]
        for label in labels
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    ]


class GitHubPullRequest(BaseModel):
    number: int
    title: str
    body: str | None = None
    state: str
    html_url: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    user_login: str | None = None
    assignee_logins: list[str] = Field(default_factory=list)
    label_names: list[str] = Field(default_factory=list)
    base_repo_full_name: str | None = None
    # True when the pull request was read on its own (``GET /pulls/{number}``).
    # Only that response has the fields below.
    detailed: bool = False
    merged: bool | None = None
    commits: int | None = None
    changed_files: int | None = None
    merged_by_login: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, detailed: bool) -> "GitHubPullRequest":
        base: Any = raw.get("base")
        base_repo: Any = base.get("repo") if isinstance(base, dict) else None
        return cls(
            number=raw["number"],
            title=raw.get("title") or "",
            body=raw.get("body"),
            state=raw.get("state") or "",
            html_url=raw["html_url"],
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            closed_at=raw.get("closed_at"),
            merged_at=raw.get("merged_at"),
            user_login=_login(raw.get("user")),
            assignee_logins=_logins(raw.get("assignees")),
            label_names=_label_names(raw.get("labels")),
            base_repo_full_name=(
                base_repo.get("full_name") if isinstance(base_repo, dict) else None
            ),
            detailed=detailed,
            merged=raw.get("merged"),
            commits=raw.get("commits"),
            changed_files=raw.get("changed_files"),
            merged_by_login=_login(raw.get("merged_by")),
        )


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str | None = None
    state: str
    html_url: str
    created_at: datetime | None = None
    updated_at: datetime
    closed_at: datetime | None = None
    # The issues API lists pull requests too.
    is_pull_request: bool = False
    user_login: str | None = None
    assignee_logins: list[str] = Field(default_factory=list)
    label_names: list[str] = Field(default_factory=list)
    repo_full_name: str
    # True when the issue was read on its own (``GET /issues/{number}``). Only
    # that response has ``closed_by``.
    detailed: bool = False
    closed_by_login: str | None = None

    @classmethod
    def from_raw(
        cls, raw: dict[str, Any], *, repo_full_name: str, detailed: bool
    ) -> "GitHubIssue":
        return cls(
            number=raw["number"],
            title=raw.get("title") or "",
            body=raw.get("body"),
            state=raw.get("state") or "",
            html_url=raw["html_url"],
            created_at=raw.get("created_at"),
            updated_at=raw["updated_at"],
            closed_at=raw.get("closed_at"),
            is_pull_request=raw.get("pull_request") is not None,
            user_login=_login(raw.get("user")),
            assignee_logins=_logins(raw.get("assignees")),
            label_names=_label_names(raw.get("labels")),
            repo_full_name=repo_full_name,
            detailed=detailed,
            closed_by_login=_login(raw.get("closed_by")),
        )


class GitHubCursorItem(BaseModel, Generic[ItemT]):
    """One item of a cursor listing, with the URL of the page after it."""

    item: ItemT
    next_url: str | None = None


class GitHubUser(BaseModel):
    login: str
    name: str | None = None
    # The public email of the profile. GitHub returns no other email.
    email: str | None = None


class GitHubTreeEntry(BaseModel):
    path: str
    type: str
    size: int | None = None


class GitHubGitTree(BaseModel):
    entries: list[GitHubTreeEntry]
    # True when GitHub cut the recursive listing (more than 100,000 entries
    # or 7 MB).
    truncated: bool = False


class GitHubFileContent(BaseModel):
    # None when GitHub does not send the content as base64 (e.g. a file over
    # 1 MB, or a Git LFS pointer).
    content: bytes | None = None
    encoding: str | None = None


class GitHubBranch(BaseModel):
    name: str


class GitHubTokenKind(str, Enum):
    # A personal access token (classic), or another token with OAuth scopes.
    CLASSIC = "classic"
    FINE_GRAINED = "fine_grained"
    # GitHub sent no scopes and the token has no known prefix.
    OTHER = "other"


class GitHubTokenInfo(BaseModel):
    login: str
    kind: GitHubTokenKind
    # The OAuth scopes of a classic token. None when GitHub sends none (a
    # fine-grained token has permissions, not scopes).
    scopes: list[str] | None = None
