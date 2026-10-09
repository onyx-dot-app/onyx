"""The connector's scope: which teams and projects it indexes, as the GraphQL
filters Linear takes and the checks that every configured entry exists."""

import re
from datetime import datetime
from typing import Any

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.linear.models import LinearProject
from onyx.connectors.linear.source_operations import LinearSourceOperations

# A project URL ends in the slug and the project's slug id:
# https://linear.app/<workspace>/project/<slug>-<slug id>
_PROJECT_URL_SLUG_ID = re.compile(
    r"linear\.app/[^/]+/project/[^/?#]*?([0-9a-f]{12})(?:[/?#]|$)"
)


def normalize_team_keys(team_keys: list[str] | None) -> list[str]:
    """Linear matches keys case-sensitively and only ever issues upper case."""
    return sorted({key.strip().upper() for key in team_keys or [] if key.strip()})


def project_scope(entries: list[str] | None) -> tuple[list[str], list[str]]:
    """The project names, and the slug ids of the entries given as URLs."""
    names: set[str] = set()
    slug_ids: set[str] = set()
    for entry in entries or []:
        entry = entry.strip()
        if not entry:
            continue
        match = _PROJECT_URL_SLUG_ID.search(entry)
        if match:
            slug_ids.add(match.group(1))
        else:
            names.add(entry)
    return sorted(names), sorted(slug_ids)


def project_filter(names: list[str], slug_ids: list[str]) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    if names:
        clauses.append({"name": {"in": names}})
    if slug_ids:
        clauses.append({"slugId": {"in": slug_ids}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"or": clauses}


def issue_filter(
    team_keys: list[str],
    projects: dict[str, Any] | None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    updated_at: dict[str, str] = {}
    if start is not None:
        updated_at["gte"] = start.isoformat()
    if end is not None:
        updated_at["lte"] = end.isoformat()
    filters: dict[str, Any] = {"updatedAt": updated_at}
    if team_keys:
        filters["team"] = {"key": {"in": team_keys}}
    if projects is not None:
        filters["project"] = projects
    return filters


def missing_team_keys(ops: LinearSourceOperations, team_keys: list[str]) -> list[str]:
    return sorted(set(team_keys) - ops.list_team_keys(keys=team_keys))


def missing_projects(
    ops: LinearSourceOperations, names: list[str], slug_ids: list[str]
) -> list[str]:
    projects: list[LinearProject] = ops.list_projects(
        project_filter=project_filter(names, slug_ids) or {}
    )
    return sorted(
        (set(names) - {project.name for project in projects})
        | (set(slug_ids) - {project.slug_id for project in projects})
    )


def scope_error(
    missing_teams: list[str], missing_projects: list[str]
) -> ConnectorValidationError:
    """An entry Linear does not answer for is misspelled or belongs to a
    private team the token's user is not in. Linear hides both the same way,
    so the message names every missing entry and the two causes."""
    problems: list[str] = []
    if missing_teams:
        problems.append(f"Linear teams not found: {', '.join(missing_teams)}.")
    if missing_projects:
        problems.append(f"Linear projects not found: {', '.join(missing_projects)}.")
    return ConnectorValidationError(
        f"{' '.join(problems)} Check each key, name or URL, or connect as a "
        "member if the team is private."
    )
