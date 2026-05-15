from slack_sdk import WebClient

from onyx.connectors.slack.utils import (
    fetch_team_user_emails as _fetch_team_user_emails,
)
from onyx.connectors.slack.utils import make_paginated_slack_api_call


def fetch_user_id_to_email_map(
    slack_client: WebClient,
    team_ids: list[str] | None = None,
) -> dict[str, str]:
    """On Grid org installs, ``users.list`` requires a ``team_id``; iterate
    every team and merge. Without ``team_ids`` (non-Grid), call once."""
    user_id_to_email_map: dict[str, str] = {}
    team_iter: list[str | None] = list(team_ids) if team_ids else [None]
    for tid in team_iter:
        kwargs: dict[str, str] = {}
        if tid:
            kwargs["team_id"] = tid
        for user_info in make_paginated_slack_api_call(
            slack_client.users_list, **kwargs
        ):
            for user in user_info.get("members", []):
                email = user.get("profile", {}).get("email")
                if email:
                    user_id_to_email_map[user.get("id")] = email
    return user_id_to_email_map


def fetch_team_user_emails(
    slack_client: WebClient,
    team_ids: list[str],
) -> dict[str, set[str]]:
    """Re-export of ``onyx.connectors.slack.utils.fetch_team_user_emails`` for
    callers that already import it from this EE module."""
    return _fetch_team_user_emails(slack_client, team_ids)
