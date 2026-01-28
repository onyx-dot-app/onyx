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
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import HierarchyNode
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
    CheckpointedConnectorWithPermSync[TeamsCheckpoint],
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

        # Check if any requested teams have special characters that need client-side filtering
        has_special_chars = _has_odata_incompatible_chars(self.requested_team_list)
        if has_special_chars:
            logger.info(
                "Some requested team names contain special characters (&, (, )) that require "
                "client-side filtering during data retrieval."
            )

        # Minimal validation: just check if we can access the teams endpoint
        timeout = 10  # Short timeout for basic validation

        try:
            # For validation, do a lightweight check instead of full team search
            logger.info(
                f"Requested team count: {len(self.requested_team_list) if self.requested_team_list else 0}, "
                f"Has special chars: {has_special_chars}"
            )

            validation_query = self.graph_client.teams.get().top(1)
            run_with_timeout(
                timeout=timeout,
                func=lambda: validation_query.execute_query(),
            )

            logger.info(
                "Teams validation successful - Access to teams endpoint confirmed"
            )

        except TimeoutError as e:
            raise ConnectorValidationError(
                f"Timeout while validating Teams access (waited {timeout}s). "
                f"This may indicate network issues or authentication problems. "
                f"Error: {e}"
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

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        # Teams already fetches external_access (permissions) for each document
        # in _convert_thread_to_document, so we can just delegate to load_from_checkpoint
        return self.load_from_checkpoint(start, end, checkpoint)

    # impls for SlimConnectorWithPermSync

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        start = start or 0

        teams = _collect_all_teams(
            graph_client=self.graph_client,
            requested=self.requested_team_list,
        )

        for team in teams:
            if not team.id:
                logger.warning(
                    f"Expected a team with an id, instead got no id: {team=}"
                )
                continue

            channels = _collect_all_channels_from_team(
                team=team,
            )

            for channel in channels:
                if not channel.id:
                    logger.warning(
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

                slim_doc_buffer: list[SlimDocument | HierarchyNode] = []

                for message in messages:
                    slim_doc_buffer.append(
                        SlimDocument(
                            id=message.id,
                            external_access=external_access,
                        )
                    )

                    if len(slim_doc_buffer) >= _SLIM_DOC_BATCH_SIZE:
                        if callback:
                            if callback.should_stop():
                                raise RuntimeError(
                                    "retrieve_all_slim_docs_perm_sync: Stop signal detected"
                                )
                            callback.progress("retrieve_all_slim_docs_perm_sync", 1)
                        yield slim_doc_buffer
                        slim_doc_buffer = []

                # Flush any remaining slim documents collected for this channel
                if slim_doc_buffer:
                    yield slim_doc_buffer
                    slim_doc_buffer = []


def _escape_odata_string(name: str) -> str:
    """Escape special characters for OData string literals.

    Uses proper OData v4 string literal escaping:
    - Single quotes: ' becomes ''
    - Other characters are handled by using contains() instead of eq for problematic cases
    """
    # Escape single quotes for OData syntax (replace ' with '')
    escaped = name.replace("'", "''")
    return escaped


def _has_odata_incompatible_chars(team_names: list[str] | None) -> bool:
    """Check if any team name contains characters that break Microsoft Graph OData filters.

    The Microsoft Graph Teams API has limited OData support. Characters like
    &, (, and ) cause parsing errors and require client-side filtering instead.
    """
    if not team_names:
        return False
    return any(char in name for name in team_names for char in ["&", "(", ")"])


def _can_use_odata_filter(
    team_names: list[str] | None,
) -> tuple[bool, list[str], list[str]]:
    """Determine which teams can use OData filtering vs client-side filtering.

    Microsoft Graph /teams endpoint OData limitations:
    - Only supports basic 'eq' operators in filters
    - No 'contains', 'startswith', or other advanced operators
    - Special characters (&, (, )) break OData parsing

    Returns:
        tuple: (can_use_odata, safe_names, problematic_names)
    """
    if not team_names:
        return False, [], []

    safe_names = []
    problematic_names = []

    for name in team_names:
        if any(char in name for char in ["&", "(", ")"]):
            problematic_names.append(name)
        else:
            safe_names.append(name)

    return bool(safe_names), safe_names, problematic_names


def _build_simple_odata_filter(safe_names: list[str]) -> str | None:
    """Build simple OData filter using only 'eq' operators for safe names."""
    if not safe_names:
        return None

    filter_parts = []
    for name in safe_names:
        escaped_name = _escape_odata_string(name)
        filter_parts.append(f"displayName eq '{escaped_name}'")

    return " or ".join(filter_parts)


def _construct_semantic_identifier(channel: Channel, top_message: Message) -> str:
    top_message_user_name: str

    if top_message.from_ and top_message.from_.user:
        user_display_name = top_message.from_.user.display_name
        top_message_user_name = (
            user_display_name if user_display_name else "Unknown User"
        )
    else:
        logger.warning(f"Message {top_message=} has no `from.user` field")
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


def _add_prefer_header(request: RequestOptions) -> None:
    """Add Prefer header to work around Microsoft Graph API ampersand bug.
    See: https://developer.microsoft.com/en-us/graph/known-issues/?search=18185
    """
    if not hasattr(request, "headers") or request.headers is None:
        request.headers = {}
    # Add header to handle properly encoded ampersands in filters
    request.headers["Prefer"] = "legacySearch=false"


def _collect_all_teams(
    graph_client: GraphClient,
    requested: list[str] | None = None,
) -> list[Team]:
    """Collect teams from Microsoft Graph using appropriate filtering strategy.

    For teams with special characters (&, (, )), uses client-side filtering
    with paginated search. For teams without special characters, uses efficient
    OData server-side filtering.

    Args:
        graph_client: Authenticated Microsoft Graph client
        requested: List of team names to find, or None for all teams

    Returns:
        List of Team objects matching the requested names
    """
    teams: list[Team] = []
    next_url: str | None = None

    # Determine filtering strategy based on Microsoft Graph limitations
    if not requested:
        # No specific teams requested - return empty list (avoid fetching all teams)
        logger.info("No specific teams requested - returning empty list")
        return []

    _, safe_names, problematic_names = _can_use_odata_filter(requested)

    if problematic_names and not safe_names:
        # ALL requested teams have special characters - cannot use OData filtering
        logger.info(
            f"All requested team names contain special characters (&, (, )) which require "
            f"client-side filtering. Using basic /teams endpoint with pagination. "
            f"Teams: {problematic_names}"
        )
        # Use unfiltered query with pagination limit to avoid fetching too many teams
        use_client_side_filtering = True
        odata_filter = None
    elif problematic_names and safe_names:
        # Mixed scenario - need to fetch more teams to find the problematic ones
        logger.info(
            f"Mixed team types: will use client-side filtering for all. "
            f"Safe names: {safe_names}, Special char names: {problematic_names}"
        )
        use_client_side_filtering = True
        odata_filter = None
    elif safe_names:
        # All names are safe - use OData filtering
        logger.info(f"Using OData filtering for all requested teams: {safe_names}")
        use_client_side_filtering = False
        odata_filter = _build_simple_odata_filter(safe_names)
    else:
        # No valid names
        return []

    # Track pagination to avoid fetching too many teams for client-side filtering
    max_pages = 200
    page_count = 0

    while True:
        try:
            if use_client_side_filtering:
                # Use basic /teams endpoint with top parameter to limit results per page
                query = graph_client.teams.get().top(50)  # Limit to 50 teams per page
            else:
                # Use OData filter with only 'eq' operators
                query = graph_client.teams.get().filter(odata_filter)

            # Add header to work around Microsoft Graph API issues
            query.before_execute(lambda req: _add_prefer_header(request=req))

            if next_url:
                url = next_url
                query.before_execute(
                    lambda req: _update_request_url(request=req, next_url=url)
                )

            team_collection = query.execute_query()
        except (ClientRequestException, ValueError) as e:
            # If OData filter fails, fall back to client-side filtering
            if not use_client_side_filtering and odata_filter:
                logger.warning(
                    f"OData filter failed: {e}. Falling back to client-side filtering."
                )
                use_client_side_filtering = True
                odata_filter = None
                teams = []
                next_url = None
                page_count = 0
                continue
            # If client-side approach also fails, re-raise
            logger.error(f"Teams query failed: {e}")
            raise

        filtered_teams = (
            team
            for team in team_collection
            if _filter_team(team=team, requested=requested)
        )
        teams.extend(filtered_teams)

        # For client-side filtering, check if we found all requested teams or hit page limit
        if use_client_side_filtering:
            page_count += 1
            found_team_names = {
                team.display_name for team in teams if team.display_name
            }
            requested_set = set(requested)

            # Log progress every 10 pages to avoid excessive logging
            if page_count % 10 == 0:
                logger.info(
                    f"Searched {page_count} pages, found {len(found_team_names)} matching teams so far"
                )

            # Stop if we found all requested teams or hit the page limit
            if requested_set.issubset(found_team_names):
                logger.info(f"Found all requested teams after {page_count} pages")
                break
            elif page_count >= max_pages:
                logger.warning(
                    f"Reached maximum page limit ({max_pages}) while searching for teams. "
                    f"Found: {found_team_names & requested_set}, "
                    f"Missing: {requested_set - found_team_names}"
                )
                break

        if not team_collection.has_next:
            break

        if not isinstance(team_collection._next_request_url, str):
            raise ValueError(
                f"The next request url field should be a string, instead got {type(team_collection._next_request_url)}"
            )

        next_url = team_collection._next_request_url

    return teams


def _normalize_team_name(name: str) -> str:
    """Normalize team name for flexible matching."""
    if not name:
        return ""
    # Convert to lowercase and strip whitespace for case-insensitive matching
    return name.lower().strip()


def _matches_requested_team(
    team_display_name: str, requested: list[str] | None
) -> bool:
    """Check if team display name matches any of the requested team names.

    Uses flexible matching to handle slight variations in team names.
    """
    if not requested or not team_display_name:
        return (
            not requested
        )  # If no teams requested, match all; if no name, don't match

    normalized_team_name = _normalize_team_name(team_display_name)

    for requested_name in requested:
        normalized_requested = _normalize_team_name(requested_name)

        # Exact match after normalization
        if normalized_team_name == normalized_requested:
            return True

        # Flexible matching - check if team name contains all significant words
        # This helps with slight variations in formatting
        team_words = set(normalized_team_name.split())
        requested_words = set(normalized_requested.split())

        # If the requested name has special characters, split on those too
        for char in ["&", "(", ")"]:
            if char in normalized_requested:
                # Split on special characters and add words
                parts = normalized_requested.replace(char, " ").split()
                requested_words.update(parts)

        # Remove very short words that aren't meaningful
        meaningful_requested_words = {
            word for word in requested_words if len(word) >= 3
        }

        # Check if team name contains most of the meaningful words
        if (
            meaningful_requested_words
            and len(meaningful_requested_words & team_words)
            >= len(meaningful_requested_words) * 0.7
        ):
            return True

    return False


def _filter_team(
    team: Team,
    requested: list[str] | None = None,
) -> bool:
    """
    Returns the true if:
        - Team is not expired / deleted
        - Team has a display-name and ID
        - Team display-name matches any of the requested teams (with flexible matching)

    Otherwise, returns false.
    """

    if not team.id or not team.display_name:
        return False

    if not _matches_requested_team(team.display_name, requested):
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
