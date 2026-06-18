import random
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from office365.graph_client import GraphClient
from office365.runtime.client_request_exception import ClientRequestException
from office365.runtime.queries.client_query import ClientQuery
from office365.teams.channels.channel import Channel
from office365.teams.channels.channel import ConversationMember

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.teams.models import Message
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()


_PUBLIC_MEMBERSHIP_TYPE = "standard"  # public teams channel


# Transient Microsoft Graph statuses worth retrying: rate limits (429) plus
# gateway/server-side hiccups (500/502/503/504). Shared by both the raw
# `execute_request_direct` path (`_retry`) and the SDK `execute_query` path
# (`execute_query_with_retry`) so the two can't drift. Mirrors the SharePoint
# connector's `GRAPH_API_RETRYABLE_STATUSES`.
GRAPH_API_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _backoff_seconds(attempt: int, retry_after: str | None) -> float:
    """Honor a server-provided ``Retry-After`` header (numeric seconds or
    HTTP-date) when present, otherwise capped exponential backoff (5s, 10s,
    20s, capped at 30s) with equal jitter so many concurrent failures don't all
    retry on the same tick.

    ``attempt`` is 0-indexed (0 for the first retry).
    """
    parsed = parse_retry_after_seconds(retry_after)
    if parsed is not None:
        return parsed
    base = min(30, (2**attempt) * 5)
    return base / 2 + random.uniform(0, base / 2)


def execute_query_with_retry(
    query: ClientQuery,
    method_name: str,
    max_retries: int = 5,
) -> Any:
    """Execute an ``office365`` SDK query, retrying transient Graph errors
    (rate limits + 5xx gateway/server hiccups) with capped backoff.

    Mirrors the SharePoint connector's ``sleep_and_retry`` so the two Microsoft
    Graph connectors behave consistently. Non-retryable statuses (e.g. 401/403/
    404, or a malformed OData filter 400) and exhausted retries are re-raised
    for the caller to handle.
    """
    for attempt in range(max_retries + 1):
        try:
            return query.execute_query()
        except ClientRequestException as e:
            status = e.response.status_code if e.response is not None else None
            if status not in GRAPH_API_RETRYABLE_STATUSES or attempt >= max_retries:
                raise

            retry_after = (
                e.response.headers.get("Retry-After")
                if e.response is not None
                else None
            )
            cooldown = _backoff_seconds(attempt=attempt, retry_after=retry_after)
            logger.warning(
                "Retryable Graph error on %s (status=%s, attempt %s/%s); "
                "sleeping %.1fs before retry.",
                method_name,
                status,
                attempt + 1,
                max_retries + 1,
                cooldown,
            )
            time.sleep(cooldown)

    # The loop returns on success and raises on non-retryable / exhausted
    # errors, so this is unreachable; it satisfies the type checker.
    raise RuntimeError(f"execute_query_with_retry exhausted retries for {method_name}")


def _sanitize_message_user_display_name(value: dict) -> dict:
    try:
        from_obj = value.get("from")
        if isinstance(from_obj, dict):
            user_obj = from_obj.get("user")
            if isinstance(user_obj, dict) and user_obj.get("displayName") is None:
                value = dict(value)
                from_obj = dict(from_obj)
                user_obj = dict(user_obj)
                user_obj["displayName"] = "Unknown User"
                from_obj["user"] = user_obj
                value["from"] = from_obj
    except (AttributeError, TypeError, KeyError):
        pass
    return value


def _retry(
    graph_client: GraphClient,
    request_url: str,
) -> dict:
    MAX_RETRIES = 10
    retry_number = 0

    while retry_number < MAX_RETRIES:
        response = graph_client.execute_request_direct(request_url)
        if response.ok:
            json = response.json()
            if not isinstance(json, dict):
                raise RuntimeError(f"Expected a JSON object, instead got {json=}")

            return json

        # Transient Graph errors (rate limits + 5xx gateway/server hiccups) are
        # retried with backoff; any other status is surfaced immediately.
        if response.status_code in GRAPH_API_RETRYABLE_STATUSES:
            cooldown = _backoff_seconds(
                attempt=retry_number,
                retry_after=response.headers.get("Retry-After"),
            )
            retry_number += 1
            # On the final permitted attempt there's nothing left to retry, so
            # don't sleep just to raise — surface the failure immediately.
            if retry_number >= MAX_RETRIES:
                break
            logger.warning(
                "Retryable Graph error %s on %s (attempt %s/%s); "
                "sleeping %.1fs before retry.",
                response.status_code,
                request_url,
                retry_number,
                MAX_RETRIES,
                cooldown,
            )
            time.sleep(cooldown)

            continue

        response.raise_for_status()

    raise RuntimeError(
        f"Max number of retries for hitting {request_url=} exceeded; unable to fetch data"
    )


def _get_next_url(
    graph_client: GraphClient,
    json_response: dict,
) -> str | None:
    next_url = json_response.get("@odata.nextLink")

    if not next_url:
        return None

    if not isinstance(next_url, str):
        raise RuntimeError(
            f"Expected a string for the `@odata.nextUrl`, instead got {next_url=}"
        )

    return next_url.removeprefix(graph_client.service_root_url()).removeprefix("/")


def _get_or_fetch_email(
    graph_client: GraphClient,
    member: ConversationMember,
) -> str | None:
    if email := member.properties.get("email"):
        return email

    user_id = member.properties.get("userId")
    if not user_id:
        logger.warning("No user-id found for this member; member=%r", member)
        return None

    json_data = _retry(graph_client=graph_client, request_url=f"users/{user_id}")
    email = json_data.get("userPrincipalName")

    if not isinstance(email, str):
        logger.warning("Expected email to be of type str, instead got email=%r", email)
        return None

    return email


def _is_channel_public(channel: Channel) -> bool:
    return (
        channel.membership_type and channel.membership_type == _PUBLIC_MEMBERSHIP_TYPE
    )


def fetch_messages(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    start: SecondsSinceUnixEpoch,
) -> Generator[Message]:
    startfmt = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    initial_request_url = f"teams/{team_id}/channels/{channel_id}/messages/delta?$filter=lastModifiedDateTime gt {startfmt}"

    request_url: str | None = initial_request_url

    while request_url:
        json_response = _retry(graph_client=graph_client, request_url=request_url)

        for value in json_response.get("value", []):
            yield Message(**_sanitize_message_user_display_name(value))

        request_url = _get_next_url(
            graph_client=graph_client, json_response=json_response
        )


def fetch_replies(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    root_message_id: str,
) -> Generator[Message]:
    initial_request_url = (
        f"teams/{team_id}/channels/{channel_id}/messages/{root_message_id}/replies"
    )

    request_url: str | None = initial_request_url

    while request_url:
        json_response = _retry(graph_client=graph_client, request_url=request_url)

        for value in json_response.get("value", []):
            yield Message(**_sanitize_message_user_display_name(value))

        request_url = _get_next_url(
            graph_client=graph_client, json_response=json_response
        )


def fetch_expert_infos(
    graph_client: GraphClient, channel: Channel
) -> list[BasicExpertInfo]:
    members = channel.members.get_all(
        # explicitly needed because of incorrect type definitions provided by the `office365` library
        page_loaded=lambda _: None
    ).execute_query_retry()

    expert_infos = []
    for member in members:
        if not member.display_name:
            logger.warning(
                "Failed to grab the display-name of member=%r; skipping", member
            )
            continue

        email = _get_or_fetch_email(graph_client=graph_client, member=member)
        if not email:
            logger.warning("Failed to grab the email of member=%r; skipping", member)
            continue

        expert_infos.append(
            BasicExpertInfo(
                display_name=member.display_name,
                email=email,
            )
        )

    return expert_infos


def fetch_external_access(
    graph_client: GraphClient,
    channel: Channel,
    expert_infos: list[BasicExpertInfo] | None = None,
) -> ExternalAccess:
    is_public = _is_channel_public(channel=channel)

    if is_public:
        return ExternalAccess.public()

    expert_infos = (
        expert_infos
        if expert_infos is not None
        else fetch_expert_infos(graph_client=graph_client, channel=channel)
    )
    emails = {expert_info.email for expert_info in expert_infos if expert_info.email}

    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=set(),
        is_public=is_public,
    )
