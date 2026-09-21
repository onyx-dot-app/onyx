import re
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import requests
from office365.graph_client import GraphClient
from office365.runtime.queries.client_query import ClientQuery

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.microsoft_utils.graph_client import (
    GRAPH_API_MAX_RETRIES,
    GRAPH_API_RETRYABLE_STATUSES,
    backoff_seconds,
    sleep_and_retry,
)
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.teams.models import ChannelFilesFolder, ChannelMember, Message
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_query_with_retry(
    build_query: Callable[[], ClientQuery],
    method_name: str,
    max_retries: int = GRAPH_API_MAX_RETRIES,
) -> Any:
    """Teams' retry policy for ``office365`` SDK queries: the wide Graph status
    set and more attempts than ``sleep_and_retry`` defaults to. Non-retryable statuses
    (401/403/404, a malformed OData filter 400) and exhausted retries re-raise
    for the caller to handle. The query is built per attempt, or a throttled
    listing would come back empty and its teams or channels would be skipped.
    """
    return sleep_and_retry(
        build_query(),
        method_name,
        max_retries=max_retries,
        retryable_statuses=GRAPH_API_RETRYABLE_STATUSES,
        rebuild=build_query,
    )


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


class ChannelFilesUnavailable(RuntimeError):
    """A channel whose files Graph describes without a document library, or a
    library without its name or site, so there is nothing to open or grant."""


class GraphRetriesExhausted(RuntimeError):
    """Graph kept answering with a retryable status for every attempt."""


def _retry(
    graph_client: GraphClient,
    request_url: str,
) -> dict:
    MAX_RETRIES = 10
    retry_number = 0

    while retry_number < MAX_RETRIES:
        # The SDK raises on every non-2xx status, so the response is taken from
        # the exception to apply one retry policy to raised and returned errors.
        try:
            response = graph_client.execute_request_direct(request_url)
        except requests.HTTPError as e:
            if e.response is None:
                raise
            response = e.response
        if response.ok:
            json = response.json()
            if not isinstance(json, dict):
                raise RuntimeError(f"Expected a JSON object, instead got {json=}")

            return json

        # Transient Graph errors (rate limits + 5xx gateway/server hiccups) are
        # retried with backoff; any other status is surfaced immediately.
        if response.status_code in GRAPH_API_RETRYABLE_STATUSES:
            cooldown = backoff_seconds(
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

    raise GraphRetriesExhausted(
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


def _iter_values(
    graph_client: GraphClient, request_url: str
) -> Generator[dict[str, Any]]:
    """Every row of a paged Graph collection."""
    url: str | None = request_url
    while url:
        json_response = _retry(graph_client=graph_client, request_url=url)
        for value in json_response.get("value", []):
            if isinstance(value, dict):
                yield value
        url = _get_next_url(graph_client=graph_client, json_response=json_response)


def _member_email(graph_client: GraphClient, member: ChannelMember) -> str | None:
    """A member row carries its email for users of any tenant. A row without
    one is looked up by user id, which only resolves users of this tenant."""
    if member.email:
        return member.email

    if not member.user_id:
        logger.warning("Channel member %r has no user id; skipping", member)
        return None

    # Only a missing user is skipped: a user of another tenant is not in this
    # directory. Any other refusal propagates, or a partial list would revoke access.
    try:
        json_data = _retry(
            graph_client=graph_client, request_url=f"users/{member.user_id}"
        )
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning(
                "Channel member %s is not in this directory; skipping",
                member.display_name,
            )
            return None
        raise

    email = json_data.get("userPrincipalName")
    if not isinstance(email, str) or not email:
        logger.warning(
            "Channel member %s has no principal name; skipping", member.user_id
        )
        return None
    return email


def fetch_channel_members(
    graph_client: GraphClient, team_id: str, channel_id: str
) -> list[ChannelMember]:
    """Everyone who can read the channel. Graph's plain members call omits the
    members a shared channel gains from the teams it is shared with, so the
    all-members call serves every channel type."""
    return [
        ChannelMember(**row)
        for row in _iter_values(
            graph_client, f"teams/{team_id}/channels/{channel_id}/allMembers"
        )
    ]


def channel_access(expert_infos: list[BasicExpertInfo]) -> ExternalAccess:
    """A channel is readable by its members and no one else. A standard channel
    is visible to its team, not the tenant, so no channel is ever public."""
    return ExternalAccess(
        external_user_emails={
            expert_info.email.lower()
            for expert_info in expert_infos
            if expert_info.email
        },
        external_user_group_ids=set(),
        is_public=False,
    )


def fetch_channel_readers(
    graph_client: GraphClient, team_id: str, channel_id: str
) -> tuple[list[BasicExpertInfo], ExternalAccess]:
    """The channel's members as document owners and as its access list."""
    expert_infos: list[BasicExpertInfo] = []
    for member in fetch_channel_members(graph_client, team_id, channel_id):
        email = _member_email(graph_client, member)
        if email is None:
            continue
        # The email is what grants access, so a member without a name still reads.
        expert_infos.append(
            BasicExpertInfo(display_name=member.display_name, email=email)
        )
    return expert_infos, channel_access(expert_infos)


# The largest page Graph serves for channel messages.
MESSAGE_PAGE_SIZE = 50


def message_delta_url(
    team_id: str, channel_id: str, start: SecondsSinceUnixEpoch
) -> str:
    startfmt = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return (
        f"teams/{team_id}/channels/{channel_id}/messages/delta"
        f"?$filter=lastModifiedDateTime gt {startfmt}&$top={MESSAGE_PAGE_SIZE}"
    )


def fetch_message_page(
    graph_client: GraphClient, request_url: str
) -> tuple[list[Message], str | None]:
    """One page of root messages and the link to the next, so a checkpoint can
    resume mid-channel."""
    json_response = _retry(graph_client=graph_client, request_url=request_url)
    messages = [
        Message(**_sanitize_message_user_display_name(value))
        for value in json_response.get("value", [])
        if isinstance(value, dict)
    ]
    return messages, _get_next_url(
        graph_client=graph_client, json_response=json_response
    )


def fetch_messages(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    start: SecondsSinceUnixEpoch,
) -> Generator[Message]:
    for value in _iter_values(
        graph_client, message_delta_url(team_id, channel_id, start)
    ):
        yield Message(**_sanitize_message_user_display_name(value))


def fetch_channel_files_folder(
    graph_client: GraphClient, team_id: str, channel_id: str
) -> ChannelFilesFolder:
    """Needs Files.Read.All or Sites.Read.All on Graph."""
    json_data = _retry(
        graph_client=graph_client,
        request_url=f"teams/{team_id}/channels/{channel_id}/filesFolder",
    )
    parent = json_data.get("parentReference") or {}
    if not parent.get("driveId"):
        raise ChannelFilesUnavailable(
            f"The files folder of channel {channel_id} names no document library"
        )
    return ChannelFilesFolder(drive_id=parent["driveId"], id=json_data["id"])


def fetch_drive_library(graph_client: GraphClient, drive_id: str) -> tuple[str, str]:
    """The document library's name, which SharePoint REST looks the list up by,
    and the url of its site. The site comes from the drive because the files
    folder can leave its own site id empty."""
    drive = _retry(
        graph_client=graph_client,
        request_url=f"drives/{drive_id}?$select=name,sharePointIds",
    )
    site_url = (drive.get("sharePointIds") or {}).get("siteUrl")
    if not drive.get("name") or not site_url:
        raise ChannelFilesUnavailable(
            f"Document library {drive_id} came back without its name or its site"
        )
    return drive["name"], site_url


# An image pasted into a message is hosted content, and its img tag points at
# the Graph route that serves the bytes. Images linked from elsewhere carry no
# such route and are left out.
_HOSTED_CONTENT_PATH = re.compile(r"/hostedContents/[^/?#]+/\$value$")


class _ImageSources(HTMLParser):
    """The src of every img tag, in body order, with entities decoded."""

    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        src = dict(attrs).get("src")
        if src:
            self.sources.append(src)


def hosted_content_urls(body_html: str, graph_root: str) -> list[str]:
    """The urls of the images pasted into a message, in body order. Only urls
    under this cloud's Graph host count: the body is user content, so a src
    shaped like a hosted content route on another host is not followed. Another
    tenant's route on the same host is asked for and refused by Graph."""
    parser = _ImageSources()
    parser.feed(body_html)
    prefix = graph_root.rstrip("/") + "/"
    return [
        src
        for src in parser.sources
        if src.startswith(prefix) and _HOSTED_CONTENT_PATH.search(src)
    ]


def fetch_replies(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    root_message_id: str,
) -> Generator[Message]:
    request_url = (
        f"teams/{team_id}/channels/{channel_id}/messages/{root_message_id}/replies"
    )

    for value in _iter_values(graph_client, request_url):
        yield Message(**_sanitize_message_user_display_name(value))
