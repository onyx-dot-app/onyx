import os
from datetime import datetime
from datetime import timezone
from typing import Any

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.teams.channels.channel import Channel  # type: ignore
from office365.teams.chats.messages.message import ChatMessage  # type: ignore
from office365.teams.team import Team  # type: ignore

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.html_utils import parse_html_page_basic
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_created_datetime(chat_message: ChatMessage) -> datetime:
    # Extract the 'createdDateTime' value from the 'properties' dictionary and convert it to a datetime object
    return time_str_to_utc(chat_message.properties["createdDateTime"])


def _extract_channel_members(channel: Channel) -> list[BasicExpertInfo]:
    channel_members_list: list[BasicExpertInfo] = []
    members = channel.members.get().execute_query()
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

    query = channel.messages.get()
    base_messages: list[ChatMessage] = query.execute_query()

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
        replies = reply_query.execute_query()

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
        query = team.channels.get()
        channels = query.execute_query()
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
        sections=[Section(link=web_url, text=thread_text)],
        source=DocumentSource.TEAMS,
        semantic_identifier=semantic_string,
        title="",  # teams threads don't really have a "title"
        doc_updated_at=most_recent_message_datetime,
        primary_owners=post_members_list,
        metadata={},
    )
    return doc


class TeamsConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        teams: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self.graph_client: GraphClient | None = None
        self.requested_team_list: list[str] = teams

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        teams_client_id = credentials["teams_client_id"]
        teams_client_secret = credentials["teams_client_secret"]
        teams_directory_id = credentials["teams_directory_id"]

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            authority_url = f"https://login.microsoftonline.com/{teams_directory_id}"
            app = msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=teams_client_id,
                client_credential=teams_client_secret,
            )
            token = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            return token

        self.graph_client = GraphClient(_acquire_token_func)
        return None

    def _get_all_teams(self) -> list[Team]:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        teams_list: list[Team] = []

        teams = self.graph_client.teams.get().execute_query()

        if len(self.requested_team_list) > 0:
            adjusted_request_strings = [
                requested_team.replace(" ", "")
                for requested_team in self.requested_team_list
            ]
            teams_list = [
                team
                for team in teams
                if team.display_name.replace(" ", "") in adjusted_request_strings
            ]
        else:
            teams_list.extend(teams)

        return teams_list

    def _fetch_from_teams(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        teams = self._get_all_teams()

        channels = _get_channels_from_teams(
            teams=teams,
        )

        # goes over channels, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for channel in channels:
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
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._fetch_from_teams(start=start_datetime, end=end_datetime)


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
