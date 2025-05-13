import contextvars
import copy
import os
from concurrent.futures import as_completed
from concurrent.futures import Future
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.runtime.client_request_exception import ClientRequestException  # type: ignore
from office365.runtime.http.request_options import RequestOptions  # type: ignore[import-untyped]
from office365.teams.channels.channel import Channel  # type: ignore
from office365.teams.chats.messages.message import ChatMessage  # type: ignore
from office365.teams.team import Team  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


class TeamsCheckpoint(ConnectorCheckpoint):
    todo_team_ids: list[str] | None = None


class TeamsConnector(
    CheckpointedConnector[TeamsCheckpoint],
):
    MAX_WORKERS = 10

    def __init__(
        self,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are NOT guaranteed to be unique
        teams: list[str] = [],
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self.graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self.max_workers = max_workers
        self.requested_team_list: list[str] = teams

    # impls for BaseConnector

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        teams_client_id = credentials["teams_client_id"]
        teams_client_secret = credentials["teams_client_secret"]
        teams_directory_id = credentials["teams_directory_id"]

        authority_url = f"https://login.microsoftonline.com/{teams_directory_id}"
        self.msal_app = msal.ConfidentialClientApplication(
            authority=authority_url,
            client_id=teams_client_id,
            client_credential=teams_client_secret,
        )

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise RuntimeError("MSAL app is not initialized")

            token = self.msal_app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )

            if not isinstance(token, dict):
                raise RuntimeError("`token` instance must be of type dict")

            return token

        self.graph_client = GraphClient(_acquire_token_func)
        return None

    def validate_connector_settings(self) -> None:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams credentials not loaded.")

        try:
            # Minimal call to confirm we can retrieve Teams
            # make sure it doesn't take forever, since this is a syncronous call
            found_teams = run_with_timeout(
                timeout=10,
                func=_collect_all_team_ids,
                graph_client=self.graph_client,
                start=0.0,
                end=datetime.now(tz=timezone.utc).timestamp(),
                requested=self.requested_team_list,
            )

        except ClientRequestException as e:
            if not e.response:
                raise RuntimeError("TODO!")
            status_code = e.response.status_code
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials (401 Unauthorized)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your app lacks sufficient permissions to read Teams (403 Forbidden)."
                )
            raise UnexpectedValidationError(f"Unexpected error retrieving teams: {e}")

        except Exception as e:
            error_str = str(e).lower()
            if (
                "unauthorized" in error_str
                or "401" in error_str
                or "invalid_grant" in error_str
            ):
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials."
                )
            elif "forbidden" in error_str or "403" in error_str:
                raise InsufficientPermissionsError(
                    "App lacks required permissions to read from Microsoft Teams."
                )
            raise ConnectorValidationError(
                f"Unexpected error during Teams validation: {e}"
            )

        if not found_teams:
            raise ConnectorValidationError(
                "No Teams found for the given credentials. "
                "Either there are no Teams in this tenant, or your app does not have permission to view them."
            )

    # impls for CheckpointedConnector

    def build_dummy_checkpoint(self) -> TeamsCheckpoint:
        return TeamsCheckpoint(
            has_more=True,
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> TeamsCheckpoint:
        return TeamsCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        checkpoint = cast(TeamsCheckpoint, copy.deepcopy(checkpoint))

        if checkpoint.todo_team_ids is None:
            root_todos = _collect_all_team_ids(
                graph_client=self.graph_client,
                start=start,
                end=end,
                requested=self.requested_team_list,
            )
            return TeamsCheckpoint(
                todo_team_ids=root_todos,
                has_more=bool(root_todos),
            )

        todos = checkpoint.todo_team_ids

        if not todos:
            return TeamsCheckpoint(
                todo_team_ids=[],
                has_more=False,
            )

        todo_team_id = todos[-1]
        team = _get_team_with_id(
            graph_client=self.graph_client,
            team_id=todo_team_id,
        )
        team_and_channel_id_pairs = _collect_all_channels_for_team_id(
            graph_client=self.graph_client,
            team=team,
        )
        todos.pop()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: list[Future[Document | None]] = []
            for team_id, channel_id in team_and_channel_id_pairs:
                curr_ctx = contextvars.copy_context()
                futures.append(
                    executor.submit(
                        curr_ctx.run,
                        _collect_document_for_channel_id,
                        graph_client=self.graph_client,
                        team=team,
                        channel_id=channel_id,
                    )
                )

            for future in as_completed(futures):
                doc = future.result()
                if doc:
                    yield doc

        return TeamsCheckpoint(
            todo_team_ids=todos,
            has_more=bool(todos),
        )


def _get_created_datetime(chat_message: ChatMessage) -> datetime:
    # Extract the 'createdDateTime' value from the 'properties' dictionary and convert it to a datetime object
    return time_str_to_utc(chat_message.properties["createdDateTime"])


def _extract_channel_members(channel: Channel) -> list[BasicExpertInfo]:
    channel_members_list: list[BasicExpertInfo] = []
    members = channel.members.get_all(page_loaded=lambda _: None).execute_query_retry()
    for member in members:
        channel_members_list.append(BasicExpertInfo(display_name=member.display_name))
    return channel_members_list


def _construct_semantic_identifier(channel: Channel, top_message: ChatMessage) -> str:
    # NOTE: needs to be done this weird way because sometime we get back `None` for
    # the fields which causes things to explode
    top_message_from = top_message.properties.get("from") or {}
    top_message_user = top_message_from.get("user") or {}
    first_poster = top_message_user.get("displayName", "Unknown User")

    channel_name = channel.properties.get("displayName", "Unknown")
    thread_subject = top_message.properties.get("subject", "Unknown")

    try:
        snippet = parse_html_page_basic(top_message.body.content.rstrip())
        snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet
    except Exception:
        logger.exception(
            f"Error parsing snippet for message "
            f"{top_message.id} with url {top_message.web_url}"
        )
        snippet = ""

    semantic_identifier = f"{first_poster} in {channel_name} about {thread_subject}"
    if snippet:
        semantic_identifier += f": {snippet}"

    return semantic_identifier


def _convert_thread_to_document(
    channel: Channel,
    thread: list[ChatMessage],
) -> Document | None:
    if len(thread) == 0:
        return None

    most_recent_message_datetime: datetime | None = None
    top_message = thread[0]
    post_members_list: list[BasicExpertInfo] = []
    thread_text = ""

    sorted_thread = sorted(thread, key=_get_created_datetime, reverse=True)

    if sorted_thread:
        most_recent_message = sorted_thread[0]
        most_recent_message_datetime = time_str_to_utc(
            most_recent_message.properties["createdDateTime"]
        )

    for message in thread:
        # add text and a newline
        if message.body.content:
            message_text = parse_html_page_basic(message.body.content)
            thread_text += message_text

        # if it has a subject, that means its the top level post message, so grab its id, url, and subject
        if message.properties["subject"]:
            top_message = message

        # check to make sure there is a valid display name
        if message.properties["from"]:
            if message.properties["from"]["user"]:
                if message.properties["from"]["user"]["displayName"]:
                    message_sender = message.properties["from"]["user"]["displayName"]
                    # if its not a duplicate, add it to the list
                    if message_sender not in [
                        member.display_name for member in post_members_list
                    ]:
                        post_members_list.append(
                            BasicExpertInfo(display_name=message_sender)
                        )

    if not thread_text:
        return None

    # if there are no found post members, grab the members from the parent channel
    if not post_members_list:
        post_members_list = _extract_channel_members(channel)

    semantic_string = _construct_semantic_identifier(channel, top_message)

    post_id = top_message.properties["id"]
    web_url = top_message.web_url

    doc = Document(
        id=post_id,
        sections=[TextSection(link=web_url, text=thread_text)],
        source=DocumentSource.TEAMS,
        semantic_identifier=semantic_string,
        title="",  # teams threads don't really have a "title"
        doc_updated_at=most_recent_message_datetime,
        primary_owners=post_members_list,
        metadata={},
    )
    return doc


def _update_request_url(request: RequestOptions, next_url: str) -> None:
    request.url = next_url


def _collect_all_team_ids(
    graph_client: GraphClient,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    requested: list[str] | None = None,
) -> list[str]:
    # The MS Office 365 Graph API does not allow you to filter on start/end datetimes server-side.
    # Instead, we do it ourselves (i.e., client-side).

    team_ids: list[str] = []
    next_url = None

    filter = None
    if requested:
        filter = " or ".join(f"displayName eq '{team_name}'" for team_name in requested)

    while True:
        if filter:
            query = graph_client.teams.get().filter(filter)
        else:
            query = graph_client.teams.get_all(page_loaded=lambda _: None)

        if next_url:
            url = next_url
            query.before_execute(
                lambda req: _update_request_url(request=req, next_url=url)
            )

        team_collection = query.execute_query()

        filtered_team_ids = [
            team_id
            for team_id in [
                _filter_team_id(team, start, end, requested) for team in team_collection
            ]
            if team_id
        ]

        team_ids.extend(filtered_team_ids)

        if team_collection.has_next:
            next_url = cast(str, team_collection._next_request_url)
        else:
            break

    return team_ids


def _filter_team_id(
    team: Team,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    requested: list[str] | None = None,
) -> str | None:
    if not team.id or not team.display_name:
        return None

    if requested and team.display_name not in requested:
        return None

    props = team.properties

    if created_at := props.get("createdDateTime"):
        if not isinstance(created_at, datetime):
            return None

        created_at_ts = created_at.replace(tzinfo=timezone.utc).timestamp()

        if created_at_ts < start or created_at_ts >= end:
            return None

    if props.get("expirationDateTime") or props.get("deletedDateTime"):
        return None

    return team.id


def _get_team_with_id(
    graph_client: GraphClient,
    team_id: str,
) -> Team:
    team_collection = (
        graph_client.teams.get().filter(f"id eq '{team_id}'").top(1).execute_query()
    )

    if not team_collection:
        raise RuntimeError(f"No team with {team_id=} was found")
    elif team_collection.has_next:
        # shouldn't happen, but catching it regardless
        raise RuntimeError(f"Multiple teams with {team_id=} were found")

    return team_collection[0]


def _collect_all_channels_for_team_id(
    graph_client: GraphClient,
    team: Team,
) -> list[tuple[str, str]]:
    if not team.id:
        raise RuntimeError(f"The {team=} has an empty `id` field")

    team_and_channel_id_pairs: list[tuple[str, str]] = []
    next_url = None

    while True:
        query = team.channels.get_all(page_loaded=lambda _: None)
        if next_url:
            url = next_url
            query = query.before_execute(
                lambda req: _update_request_url(request=req, next_url=url)
            )

        channel_collection = query.execute_query()
        team_and_channel_id_pairs.extend(
            [(team.id, channel.id) for channel in channel_collection if channel.id]
        )

        if not channel_collection.has_next:
            break

    return team_and_channel_id_pairs


def _collect_document_for_channel_id(
    graph_client: GraphClient,
    team: Team,
    channel_id: str,
) -> Document | None:
    if not team.id:
        raise RuntimeError(f"The {team=} does not have an id associated with it")

    channel_collection = (
        team.channels.get().filter(f"id eq '{channel_id}'").execute_query()
    )
    channel = channel_collection[0]

    message_collection = channel.messages.get_all(
        page_loaded=lambda _: None
    ).execute_query()

    return _convert_thread_to_document(
        channel=channel,
        thread=list(message_collection),
    )


if __name__ == "__main__":
    from tests.daily.connectors.utils import load_everything_from_checkpoint_connector

    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    teams_env_var = os.environ.get("TEAMS", None)
    teams = teams_env_var.split(",") if teams_env_var else []
    connector = TeamsConnector(teams=teams)

    connector.load_credentials(
        {
            "teams_client_id": app_id,
            "teams_directory_id": dir_id,
            "teams_client_secret": secret,
        }
    )

    connector.validate_connector_settings()

    print(
        load_everything_from_checkpoint_connector(
            connector=connector,
            start=0.0,
            end=datetime.now(tz=timezone.utc).timestamp(),
        )
    )
