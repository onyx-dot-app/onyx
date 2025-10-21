import copy
import os
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.runtime.client_request_exception import ClientRequestException  # type: ignore
from office365.runtime.http.request_options import RequestOptions  # type: ignore[import-untyped]
from office365.teams.channels.channel import Channel  # type: ignore
from office365.teams.team import Team  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.teams.models import Message
from onyx.connectors.teams.utils import fetch_expert_infos
from onyx.connectors.teams.utils import fetch_external_access
from onyx.connectors.teams.utils import fetch_messages
from onyx.connectors.teams.utils import fetch_replies
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

_SLIM_DOC_BATCH_SIZE = 5000


class TeamsCheckpoint(ConnectorCheckpoint):
    todo_team_ids: list[str] | None = None


class TeamsConnector(
    CheckpointedConnector[TeamsCheckpoint],
    SlimConnectorWithPermSync,
):
    MAX_WORKERS = 10
    AUTHORITY_URL_PREFIX = "https://login.microsoftonline.com/"

    def __init__(
        self,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are not necessarily guaranteed to be unique
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

        authority_url = f"{TeamsConnector.AUTHORITY_URL_PREFIX}{teams_directory_id}"
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
                func=_collect_all_teams,
                graph_client=self.graph_client,
                requested=self.requested_team_list,
            )

        except ClientRequestException as e:
            if not e.response:
                raise RuntimeError(f"No response provided in error; {e=}")
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

        todos = checkpoint.todo_team_ids

        if todos is None:
            teams = _collect_all_teams(
                graph_client=self.graph_client,
                requested=self.requested_team_list,
            )
            todo_team_ids = [team.id for team in teams if team.id]
            return TeamsCheckpoint(
                todo_team_ids=todo_team_ids,
                has_more=bool(todo_team_ids),
            )

        # `todos.pop()` should always return an element. This is because if
        # `todos` was the empty list, then we would have set `has_more=False`
        # during the previous invocation of `TeamsConnector.load_from_checkpoint`,
        # meaning that this function wouldn't have been called in the first place.
        todo_team_id = todos.pop()
        team = _get_team_by_id(
            graph_client=self.graph_client,
            team_id=todo_team_id,
        )
        channels = _collect_all_channels_from_team(
            team=team,
        )

        # An iterator of channels, in which each channel is an iterator of docs.
        channels_docs = [
            _collect_documents_for_channel(
                graph_client=self.graph_client,
                team=team,
                channel=channel,
                start=start,
            )
            for channel in channels
        ]

        # Was previously `for doc in parallel_yield(gens=docs, max_workers=self.max_workers): ...`.
        # However, that lead to some weird exceptions (potentially due to non-thread-safe behaviour in the Teams library).
        # Reverting back to the non-threaded case for now.
        for channel_docs in channels_docs:
            for channel_doc in channel_docs:
                if channel_doc:
                    yield channel_doc

        logger.info(
            f"Processed team with id {todo_team_id}; {len(todos)} team(s) left to process"
        )

        return TeamsCheckpoint(
            todo_team_ids=todos,
            has_more=bool(todos),
        )

    # impls for SlimConnectorWithPermSync

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        start = start or 0

        teams = _collect_all_teams(
            graph_client=self.graph_client,
            requested=self.requested_team_list,
        )

        for team in teams:
            if not team.id:
                logger.warn(f"Expected a team with an id, instead got no id: {team=}")
                continue

            channels = _collect_all_channels_from_team(
                team=team,
            )

            for channel in channels:
                if not channel.id:
                    logger.warn(
                        f"Expected a channel with an id, instead got no id: {channel=}"
                    )
                    continue

                external_access = fetch_external_access(
                    graph_client=self.graph_client, channel=channel
                )

                messages = fetch_messages(
                    graph_client=self.graph_client,
                    team_id=team.id,
                    channel_id=channel.id,
                    start=start,
                )

                slim_doc_buffer = []

                for message in messages:
                    slim_doc_buffer.append(
                        SlimDocument(
                            id=message.id,
                            external_access=external_access,
                        )
                    )

                    if len(slim_doc_buffer) >= _SLIM_DOC_BATCH_SIZE:
                        yield slim_doc_buffer
                        slim_doc_buffer = []

                # Flush any remaining slim documents collected for this channel
                if slim_doc_buffer:
                    yield slim_doc_buffer
                    slim_doc_buffer = []


def _construct_semantic_identifier(channel: Channel, top_message: Message) -> str:
    top_message_user_name: str

    if top_message.from_ and top_message.from_.user:
        user_display_name = top_message.from_.user.display_name
        top_message_user_name = (
            user_display_name if user_display_name else "Unknown User"
        )
    else:
        logger.warn(f"Message {top_message=} has no `from.user` field")
        top_message_user_name = "Unknown User"

    top_message_content = top_message.body.content or ""
    top_message_subject = top_message.subject or "Unknown Subject"
    channel_name = channel.properties.get("displayName", "Unknown")

    try:
        snippet = parse_html_page_basic(top_message_content.rstrip())
        snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet

    except Exception:
        logger.exception(
            f"Error parsing snippet for message "
            f"{top_message.id} with url {top_message.web_url}"
        )
        snippet = ""

    semantic_identifier = (
        f"{top_message_user_name} in {channel_name} about {top_message_subject}"
    )
    if snippet:
        semantic_identifier += f": {snippet}"

    return semantic_identifier


def _convert_thread_to_document(
    graph_client: GraphClient,
    channel: Channel,
    thread: list[Message],
) -> Document | None:
    if len(thread) == 0:
        return None

    most_recent_message_datetime: datetime | None = None
    top_message = thread[0]
    thread_text = ""

    sorted_thread = sorted(thread, key=lambda m: m.created_date_time, reverse=True)

    if sorted_thread:
        most_recent_message_datetime = sorted_thread[0].created_date_time

    for message in thread:
        # Add text and a newline
        if message.body.content:
            thread_text += parse_html_page_basic(message.body.content)

        # If it has a subject, that means its the top level post message, so grab its id, url, and subject
        if message.subject:
            top_message = message

    if not thread_text:
        return None

    semantic_string = _construct_semantic_identifier(channel, top_message)
    expert_infos = fetch_expert_infos(graph_client=graph_client, channel=channel)
    external_access = fetch_external_access(
        graph_client=graph_client, channel=channel, expert_infos=expert_infos
    )

    return Document(
        id=top_message.id,
        sections=[TextSection(link=top_message.web_url, text=thread_text)],
        source=DocumentSource.TEAMS,
        semantic_identifier=semantic_string,
        title="",  # teams threads don't really have a "title"
        doc_updated_at=most_recent_message_datetime,
        primary_owners=expert_infos,
        metadata={},
        external_access=external_access,
    )


def _update_request_url(request: RequestOptions, next_url: str) -> None:
    request.url = next_url


def _collect_all_teams(
    graph_client: GraphClient,
    requested: list[str] | None = None,
) -> list[Team]:
    teams: list[Team] = []
    next_url: str | None = None

    # Only use OData filter if team names don't have special characters
    # These chars are known to cause OData/URL encoding issues: &'\"?#%+=/\
    problematic_chars = "&'\"?#%+=/\\"
    use_filter = requested and not any(
        c in name for name in requested for c in problematic_chars
    )
    filter = None
    if use_filter and requested:
        escaped_names = [name.replace("'", "''") for name in requested]
        filter = " or ".join(
            f"displayName eq '{team_name}'" for team_name in escaped_names
        )

    while True:
        try:
            if filter:
                query = graph_client.teams.get().filter(filter)
            else:
                query = graph_client.teams.get_all(
                    # explicitly needed because of incorrect type definitions provided by the `office365` library
                    page_loaded=lambda _: None
                )

            if next_url:
                url = next_url
                query.before_execute(
                    lambda req: _update_request_url(request=req, next_url=url)
                )

            team_collection = query.execute_query()
        except (ClientRequestException, ValueError) as e:
            # If OData filter fails, fallback to client-side filtering
            if use_filter:
                logger.warning(
                    f"OData filter failed with {type(e).__name__}: {e}. "
                    f"Falling back to client-side filtering."
                )
                use_filter = False
                filter = None
                teams = []
                next_url = None
                continue
            raise

        filtered_teams = (
            team
            for team in team_collection
            if _filter_team(team=team, requested=requested)
        )
        teams.extend(filtered_teams)

        if not team_collection.has_next:
            break

        if not isinstance(team_collection._next_request_url, str):
            raise ValueError(
                f"The next request url field should be a string, instead got {type(team_collection._next_request_url)}"
            )

        next_url = team_collection._next_request_url

    return teams


def _filter_team(
    team: Team,
    requested: list[str] | None = None,
) -> bool:
    """
    Returns the true if:
        - Team is not expired / deleted
        - Team has a display-name and ID
        - Team display-name is in the requested teams list

    Otherwise, returns false.
    """

    if not team.id or not team.display_name:
        return False

    if requested and team.display_name not in requested:
        return False

    props = team.properties

    expiration = props.get("expirationDateTime")
    deleted = props.get("deletedDateTime")

    # We just check for the existence of those two fields, not their actual dates.
    # This is because if these fields do exist, they have to have occurred in the past, thus making them already
    # expired / deleted.
    return not expiration and not deleted


def _get_team_by_id(
    graph_client: GraphClient,
    team_id: str,
) -> Team:
    team_collection = (
        graph_client.teams.get().filter(f"id eq '{team_id}'").top(1).execute_query()
    )

    if not team_collection:
        raise ValueError(f"No team with {team_id=} was found")
    elif team_collection.has_next:
        # shouldn't happen, but catching it regardless
        raise RuntimeError(f"Multiple teams with {team_id=} were found")

    return team_collection[0]


def _collect_all_channels_from_team(
    team: Team,
) -> list[Channel]:
    if not team.id:
        raise RuntimeError(f"The {team=} has an empty `id` field")

    channels: list[Channel] = []
    next_url = None

    while True:
        query = team.channels.get_all(
            # explicitly needed because of incorrect type definitions provided by the `office365` library
            page_loaded=lambda _: None
        )
        if next_url:
            url = next_url
            query = query.before_execute(
                lambda req: _update_request_url(request=req, next_url=url)
            )

        channel_collection = query.execute_query()
        channels.extend(channel for channel in channel_collection if channel.id)

        if not channel_collection.has_next:
            break

    return channels


def _collect_documents_for_channel(
    graph_client: GraphClient,
    team: Team,
    channel: Channel,
    start: SecondsSinceUnixEpoch,
) -> Iterator[Document | None | ConnectorFailure]:
    """
    This function yields an iterator of `Document`s, where each `Document` corresponds to a "thread".

    A "thread" is the conjunction of the "root" message and all of its replies.
    """

    for message in fetch_messages(
        graph_client=graph_client,
        team_id=team.id,
        channel_id=channel.id,
        start=start,
    ):
        try:
            replies = list(
                fetch_replies(
                    graph_client=graph_client,
                    team_id=team.id,
                    channel_id=channel.id,
                    root_message_id=message.id,
                )
            )

            thread = [message]
            thread.extend(replies[::-1])

            # Note:
            # We convert an entire *thread* (including the root message and its replies) into one, singular `Document`.
            # I.e., we don't convert each individual message and each individual reply into their own individual `Document`s.
            if doc := _convert_thread_to_document(
                graph_client=graph_client,
                channel=channel,
                thread=thread,
            ):
                yield doc

        except Exception as e:
            yield ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=message.id,
                ),
                failure_message=f"Retrieval of message and its replies failed; {channel.id=} {message.id}",
                exception=e,
            )


if __name__ == "__main__":
    from tests.daily.connectors.utils import load_everything_from_checkpoint_connector

    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    teams_env_var = os.environ.get("TEAMS", None)
    teams = teams_env_var.split(",") if teams_env_var else []

    teams_connector = TeamsConnector(teams=teams)
    teams_connector.load_credentials(
        {
            "teams_client_id": app_id,
            "teams_directory_id": dir_id,
            "teams_client_secret": secret,
        }
    )
    teams_connector.validate_connector_settings()

    for slim_doc in teams_connector.retrieve_all_slim_docs_perm_sync():
        ...

    for doc in load_everything_from_checkpoint_connector(
        connector=teams_connector,
        start=0.0,
        end=datetime.now(tz=timezone.utc).timestamp(),
    ):
        print(doc)
