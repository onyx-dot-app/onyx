"""The permission-aware side of the Linear connector: who may read each
issue, the teams and members behind the groups, and the guest probe. Every
line here exists only to sync Linear permissions, so it lives in EE on top
of the Community Edition connector's indexing and credential handling."""

from typing import Any

from ee.onyx.external_permissions.linear.access import (
    SharedAccessIndex,
    issue_access,
    member_emails,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.linear.connector import (
    PAGE_INFO,
    LinearConnector,
    LinearGraphQLError,
    run_query,
)
from onyx.connectors.linear.models import (
    IssueShare,
    LinearTeam,
    LinearUser,
    WorkspaceMembers,
)
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A page of these access fields fits under the complexity cap at 250 issues.
_ACCESS_PAGE_SIZE = 250
# Every walked issue id stays in memory until the walk ends, with the shares
# that name anyone. Past this many the workspace is worth a look.
_RETAINED_ISSUES_WARNING: int = 250_000
_USER_FIELDS = "email active guest app"

_ISSUE_ACCESS_QUERY = f"""
    query IterateIssueAccess($first: Int, $after: String, $filter: IssueFilter) {{
        organization {{ id }}
        issues(orderBy: updatedAt, first: $first, after: $after, filter: $filter) {{
            nodes {{
                id
                inheritsSharedAccess
                parent {{ id }}
                team {{ id key visibility parent {{ id }} }}
                sharedAccess {{ sharedWithUsers {{ {_USER_FIELDS} }} }}
            }}
            {PAGE_INFO}
        }}
    }}
"""
_TEAMS_QUERY = f"""
    query IterateTeams($first: Int, $after: String) {{
        teams(first: $first, after: $after) {{
            nodes {{ id key visibility parent {{ id }} }}
            {PAGE_INFO}
        }}
    }}
"""
_TEAM_MEMBERS_QUERY = f"""
    query IterateTeamMembers($teamId: String!, $first: Int, $after: String) {{
        team(id: $teamId) {{
            memberships(first: $first, after: $after) {{
                nodes {{ user {{ {_USER_FIELDS} }} }}
                {PAGE_INFO}
            }}
        }}
    }}
"""
_USERS_QUERY = f"""
    query IterateUsers($first: Int, $after: String) {{
        organization {{ id userCount }}
        users(first: $first, after: $after) {{
            nodes {{ {_USER_FIELDS} }}
            {PAGE_INFO}
        }}
    }}
"""
_ISSUE_SHARE_QUERY = f"""
    query IssueShare($id: String!) {{
        issue(id: $id) {{
            inheritsSharedAccess
            parent {{ id }}
            sharedAccess {{ sharedWithUsers {{ {_USER_FIELDS} }} }}
        }}
    }}
"""
_VIEWER_QUERY = "query Viewer { viewer { guest } }"


def _share(node: dict[str, Any]) -> IssueShare:
    parent: dict[str, Any] | None = node["parent"]
    return IssueShare(
        parent_id=parent["id"] if parent else None,
        inherits=node["inheritsSharedAccess"],
        emails=member_emails(
            LinearUser.model_validate(user)
            for user in node["sharedAccess"]["sharedWithUsers"]
        ),
    )


def _team(node: dict[str, Any]) -> LinearTeam:
    parent: dict[str, Any] | None = node["parent"]
    return LinearTeam(
        id=node["id"],
        key=node["key"],
        visibility=node["visibility"],
        parent_id=parent["id"] if parent else None,
    )


class LinearPermSyncConnector(LinearConnector, SlimConnectorWithPermSync):
    """The connector with its permission walk and membership listings."""

    @classmethod
    def from_connector(cls, connector: LinearConnector) -> "LinearPermSyncConnector":
        """The twin of a connector the factory built, on the same credential
        provider, for the probe that runs before each scheduled sync."""
        twin = cls(
            team_keys=connector.team_keys,
            projects=connector.projects,
            batch_size=connector.batch_size,
        )
        twin.set_credentials_provider(connector.credentials_provider)
        return twin

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        """Every issue the token can read, with who may read it. The doc sync
        makes any indexed issue this does not list private, so the window is
        ignored. A sub-issue that inherits sharing waits for the walk to end,
        since its parent can page after it."""
        shares: SharedAccessIndex = SharedAccessIndex(self._issue_share)
        warned: bool = False
        inheriting: list[tuple[str, LinearTeam]] = []
        organization_id: str = ""
        for data in self._pages(
            _ISSUE_ACCESS_QUERY,
            {"filter": self._issue_filter()},
            ("issues",),
            _ACCESS_PAGE_SIZE,
        ):
            organization_id = data["organization"]["id"]
            docs: list[SlimDocument | HierarchyNode] = []
            for node in data["issues"]["nodes"]:
                team: LinearTeam = _team(node["team"])
                share: IssueShare = _share(node)
                shares.record(node["id"], share)
                if share.inherits:
                    inheriting.append((node["id"], team))
                    continue
                docs.append(
                    SlimDocument(
                        id=node["id"],
                        external_access=issue_access(
                            team, organization_id, share.emails
                        ),
                    )
                )
            yield docs
            if not warned and len(shares) > _RETAINED_ISSUES_WARNING:
                warned = True
                logger.warning(
                    "Linear permission sync is keeping %s walked issues in memory "
                    "until the walk ends",
                    len(shares),
                )
        for start in range(0, len(inheriting), _ACCESS_PAGE_SIZE):
            yield [
                SlimDocument(
                    id=issue_id,
                    external_access=issue_access(
                        team, organization_id, shares.emails_for(issue_id)
                    ),
                )
                for issue_id, team in inheriting[start : start + _ACCESS_PAGE_SIZE]
            ]

    def _issue_share(self, issue_id: str) -> IssueShare:
        """The shares of an ancestor the scoped walk left out. One the token
        cannot see grants nothing, which is the safe side for access. Any
        other failure raises, so an outage never reads as revoked access."""
        try:
            data: dict[str, Any] = run_query(
                _ISSUE_SHARE_QUERY, {"id": issue_id}, self._api_key()
            )
        except LinearGraphQLError as e:
            if not e.is_not_found:
                raise
            logger.warning(
                "Linear parent issue %s is not visible to the token, so its "
                "sub-issues inherit no shared readers",
                issue_id,
            )
            return IssueShare(parent_id=None, inherits=False, emails=set())
        return _share(data["issue"])

    def list_teams(self) -> list[LinearTeam]:
        return [
            _team(node)
            for data in self._pages(_TEAMS_QUERY, {}, ("teams",))
            for node in data["teams"]["nodes"]
        ]

    def team_member_emails(self, team_id: str) -> set[str]:
        return member_emails(
            LinearUser.model_validate(node["user"])
            for data in self._pages(
                _TEAM_MEMBERS_QUERY, {"teamId": team_id}, ("team", "memberships")
            )
            for node in data["team"]["memberships"]["nodes"]
        )

    def workspace_members(self) -> WorkspaceMembers:
        """Raises on a listing shorter than the workspace's own count: a group
        filled from part of it would revoke access for everyone left out."""
        users: list[LinearUser] = []
        expected: int = 0
        organization_id: str = ""
        for data in self._pages(_USERS_QUERY, {}, ("users",)):
            organization_id = data["organization"]["id"]
            expected = data["organization"]["userCount"]
            users.extend(
                LinearUser.model_validate(node) for node in data["users"]["nodes"]
            )
        if len(users) < expected:
            raise RuntimeError(
                f"Linear listed {len(users)} of the {expected} users it reported"
            )
        return WorkspaceMembers(
            organization_id=organization_id,
            emails=member_emails(user for user in users if not user.guest),
        )

    def probe_perm_sync_access(self) -> None:
        """Raises for a guest token, which cannot see the workspace's members."""
        if run_query(_VIEWER_QUERY, {}, self._api_key())["viewer"]["guest"]:
            raise InsufficientPermissionsError(
                "The connected Linear user is a guest. Connect as a workspace "
                "member who belongs to every private team to index."
            )


def linear_connector(cc_pair: ConnectorCredentialPair) -> LinearPermSyncConnector:
    """The pair's connector on the DB credential provider, whose rotation lock
    and write-back keep a refreshed OAuth token shared with indexing."""
    connector = LinearPermSyncConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.set_credentials_provider(
        build_db_credentials_provider(DocumentSource.LINEAR, cc_pair.credential.id)
    )
    return connector
