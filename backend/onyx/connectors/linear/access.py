"""Who may read a Linear issue: its team's members, every workspace member
for a public team, the private parent's members too for a restricted
sub-team, and the people the issue is shared with. Sharing covers the whole
sub-issue tree, so a sub-issue that inherits takes its ancestors' people."""

from collections.abc import Callable, Iterable

from onyx.access.models import ExternalAccess
from onyx.connectors.linear.models import (
    IssueShare,
    LinearTeam,
    LinearUser,
    TeamVisibility,
)

# Sub-issues nest a few levels, so this only stops a cycle in the data from
# looping forever.
_MAX_ANCESTOR_DEPTH = 100


def workspace_members_group_id(organization_id: str) -> str:
    """Active people who are not guests. Named by the workspace so two Linear
    workspaces in one tenant do not read each other's public teams. A guest
    only sees the teams they were added to, which the team groups cover."""
    return f"workspace_members:{organization_id}"


def member_emails(users: Iterable[LinearUser]) -> set[str]:
    """Deactivated users keep their membership rows and an app user is nobody
    to grant, so both are left out."""
    emails = (
        user.email.strip().lower() for user in users if user.active and not user.app
    )
    return {email for email in emails if email}


def issue_access(
    team: LinearTeam, organization_id: str, shared_emails: set[str]
) -> ExternalAccess:
    groups: set[str] = {team.id}
    if team.visibility is TeamVisibility.PUBLIC:
        groups.add(workspace_members_group_id(organization_id))
    elif team.visibility is TeamVisibility.RESTRICTED:
        if team.parent_id is None:
            raise ValueError(f"Linear restricted team {team.key} has no parent team")
        groups.add(team.parent_id)
    return ExternalAccess(
        external_user_emails=shared_emails,
        external_user_group_ids=groups,
        is_public=False,
    )


class SharedAccessIndex:
    """The shares of every issue that names anyone or inherits, kept until the
    walk ends because a sub-issue can page before its parent. An ancestor the
    walk never saw, because a scoped connector left its team or project out,
    is read on demand through `load` and kept for the next sub-issue."""

    def __init__(self, load: Callable[[str], IssueShare]) -> None:
        self._shares: dict[str, IssueShare] = {}
        self._seen: set[str] = set()
        self._load = load

    def record(self, issue_id: str, share: IssueShare) -> None:
        self._seen.add(issue_id)
        if share.emails or share.inherits:
            self._shares[issue_id] = share

    def __len__(self) -> int:
        return len(self._shares)

    def emails_for(self, issue_id: str) -> set[str]:
        emails: set[str] = set()
        current: str | None = issue_id
        for _ in range(_MAX_ANCESTOR_DEPTH):
            if current is None:
                return emails
            if current not in self._seen:
                self.record(current, self._load(current))
            share: IssueShare | None = self._shares.get(current)
            if share is None:
                return emails
            emails |= share.emails
            if not share.inherits:
                return emails
            current = share.parent_id
        raise ValueError(
            f"Linear issue {issue_id} has more than {_MAX_ANCESTOR_DEPTH} ancestors"
        )
