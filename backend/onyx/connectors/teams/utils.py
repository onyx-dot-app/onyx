import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from http import HTTPStatus

from office365.graph_client import GraphClient  # type: ignore
from office365.teams.channels.channel import Channel  # type: ignore
from office365.teams.channels.channel import ConversationMember  # type: ignore

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.teams.models import Message
from onyx.utils.logger import setup_logger

logger = setup_logger()


_PUBLIC_MEMBERSHIP_TYPE = "standard"  # public teams channel


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

        if response.status_code == int(HTTPStatus.TOO_MANY_REQUESTS):
            retry_number += 1

            cooldown = int(response.headers.get("Retry-After", 10))
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
        logger.warn(f"No user-id found for this member; {member=}")
        return None

    json_data = _retry(graph_client=graph_client, request_url=f"users/{user_id}")
    email = json_data.get("userPrincipalName")

    if not isinstance(email, str):
        logger.warn(f"Expected email to be of type str, instead got {email=}")
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

    initial_request_url = (
        f"teams/{team_id}/channels/{channel_id}/messages/delta"
        f"?$filter=lastModifiedDateTime gt {startfmt}"
    )

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
            logger.warn(f"Failed to grab the display-name of {member=}; skipping")
            continue

        email = _get_or_fetch_email(graph_client=graph_client, member=member)
        if not email:
            logger.warn(f"Failed to grab the email of {member=}; skipping")
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
