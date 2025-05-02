import os
from datetime import datetime
from datetime import timezone
from typing import Any

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.runtime.client_request_exception import ClientRequestException  # type: ignore
from office365.teams.channels.channel import Channel  # type: ignore
from office365.teams.chats.messages.message import ChatMessage  # type: ignore
from office365.teams.team import Team  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def get_created_datetime(chat_message: ChatMessage) -> datetime:
    # Extract the 'createdDateTime' value from the 'properties' dictionary and convert it to a datetime object
    return time_str_to_utc(chat_message.properties["createdDateTime"])


def _extract_channel_members(channel: Channel) -> list[BasicExpertInfo]:
    channel_members_list: list[BasicExpertInfo] = []
    members = channel.members.get_all().execute_query_retry()
    for member in members:
        channel_members_list.append(BasicExpertInfo(display_name=member.display_name))
    return channel_members_list


def _get_threads_from_channel(
    channel: Channel,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[list[ChatMessage]]:
    # Ensure start and end are timezone-aware
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    query = channel.messages.get_all()
    base_messages: list[ChatMessage] = query.execute_query_retry()

    threads: list[list[ChatMessage]] = []
    for base_message in base_messages:
        message_datetime = time_str_to_utc(
            base_message.properties["lastModifiedDateTime"]
        )

        if start and message_datetime < start:
            continue
        if end and message_datetime > end:
            continue

        reply_query = base_message.replies.get_all()
        replies = reply_query.execute_query_retry()

        # start a list containing the base message and its replies
        thread: list[ChatMessage] = [base_message]
        thread.extend(replies)

        threads.append(thread)

    return threads


def _get_channels_from_teams(
    teams: list[Team],
) -> list[Channel]:
    channels_list: list[Channel] = []
    for team in teams:
        query = team.channels.get_all()
        channels = query.execute_query_retry()
        channels_list.extend(channels)

    return channels_list


def _construct_semantic_identifier(channel: Channel, top_message: ChatMessage) -> str:
    first_poster = (
        top_message.properties.get("from", {})
        .get("user", {})
        .get("displayName", "Unknown User")
    )
    channel_name = channel.properties.get("displayName", "Unknown")
    thread_subject = top_message.properties.get("subject", "Unknown")

    snippet = parse_html_page_basic(top_message.body.content.rstrip())
    snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet

    return f"{first_poster} in {channel_name} about {thread_subject}: {snippet}"


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

    sorted_thread = sorted(thread, key=get_created_datetime, reverse=True)

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

    # if there are no found post members, grab the members from the parent channel
    if not post_members_list:
        post_members_list = _extract_channel_members(channel)

    if not thread_text:
        return None

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


class TeamsConnector(LoadConnector, PollConnector):
    MAX_CHANNELS_TO_LOG = 50

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are NOT guaranteed to be unique
        teams: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self.graph_client: GraphClient | None = None
        self.requested_team_list: list[str] = teams
        self.msal_app: msal.ConfidentialClientApplication | None = None

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
            return token

        self.graph_client = GraphClient(_acquire_token_func)
        return None

    def _get_all_teams(self) -> list[Team]:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        teams: list[Team] = []
        try:
            # Use get_all() to handle pagination automatically
            if not self.requested_team_list:
                teams = self.graph_client.teams.get_all().execute_query()
            else:
                # Construct filter using proper Microsoft Graph API syntax
                filter_conditions = " or ".join(
                    [
                        f"displayName eq '{team_name}'"
                        for team_name in self.requested_team_list
                    ]
                )

                # Initialize pagination variables
                page_size = 100  # Maximum allowed by Microsoft Graph API
                skip = 0

                while True:
                    # Get a page of teams with the filter
                    teams_page = (
                        self.graph_client.teams.get()
                        .filter(filter_conditions)
                        .top(page_size)
                        .skip(skip)
                        .execute_query()
                    )

                    if not teams_page:
                        break

                    teams.extend(teams_page)
                    skip += page_size

                    # If we got fewer results than the page size, we've reached the end
                    if len(teams_page) < page_size:
                        break

                # Validate that we found all requested teams
                if len(teams) != len(self.requested_team_list):
                    found_team_names = {
                        team.properties["displayName"] for team in teams
                    }
                    missing_teams = set(self.requested_team_list) - found_team_names
                    raise ConnectorValidationError(
                        f"Requested teams not found: {list(missing_teams)}"
                    )
        except ClientRequestException as e:
            if e.response.status_code == 403:
                raise InsufficientPermissionsError(
                    "App lacks required permissions to read Teams. "
                    "Please ensure the app has the following permissions: "
                    "Team.ReadBasic.All, TeamMember.Read.All, "
                    "Channel.ReadBasic.All, ChannelMessage.Read.All, "
                    "Group.Read.All, TeamSettings.ReadWrite.All, "
                    "ChannelMember.Read.All, ChannelSettings.ReadWrite.All"
                )
            raise

        return teams

    def _fetch_from_teams(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        teams = self._get_all_teams()
        logger.debug(f"Found available teams: {[str(t) for t in teams]}")
        if not teams:
            msg = "No teams found."
            logger.error(msg)
            raise ValueError(msg)

        channels = _get_channels_from_teams(
            teams=teams,
        )

        logger.debug(
            f"Found available channels (max {TeamsConnector.MAX_CHANNELS_TO_LOG} shown): "
            f"{[c.id for c in channels[:TeamsConnector.MAX_CHANNELS_TO_LOG]]}"
        )
        if not channels:
            msg = "No channels found."
            logger.error(msg)
            raise ValueError(msg)

        # goes over channels, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for channel in channels:
            logger.info(f"Fetching threads from channel: {channel.id}")
            thread_list = _get_threads_from_channel(channel, start=start, end=end)
            for thread in thread_list:
                converted_doc = _convert_thread_to_document(channel, thread)
                if converted_doc:
                    doc_batch.append(converted_doc)

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []
        yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_teams()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, timezone.utc)
        end_datetime = datetime.fromtimestamp(end, timezone.utc)
        return self._fetch_from_teams(start=start_datetime, end=end_datetime)

    def validate_connector_settings(self) -> None:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams credentials not loaded.")

        try:
            # Minimal call to confirm we can retrieve Teams
            # make sure it doesn't take forever, since this is a syncronous call
            found_teams = run_with_timeout(10, self._get_all_teams)

        except ClientRequestException as e:
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


if __name__ == "__main__":
    connector = TeamsConnector(teams=os.environ["TEAMS"].split(","))

    connector.load_credentials(
        {
            "teams_client_id": os.environ["TEAMS_CLIENT_ID"],
            "teams_client_secret": os.environ["TEAMS_CLIENT_SECRET"],
            "teams_directory_id": os.environ["TEAMS_CLIENT_DIRECTORY_ID"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
