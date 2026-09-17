import copy
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from functools import partial
from typing import Any

import msal
import requests
from office365.graph_client import GraphClient
from office365.runtime.client_request_exception import ClientRequestException
from office365.runtime.http.request_options import RequestOptions
from office365.teams.channels.channel import Channel
from office365.teams.team import Team

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.teams.models import ChannelRef, Message
from onyx.connectors.teams.utils import (
    execute_query_with_retry,
    fetch_channel_readers,
    fetch_message_page,
    fetch_messages,
    fetch_replies,
    message_delta_url,
)
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

_SLIM_DOC_BATCH_SIZE = 5000


class TeamsCheckpoint(ConnectorCheckpoint):
    # None until the teams are listed.
    todo_team_ids: list[str] | None = None
    todo_channels: list[ChannelRef] = []
    # A step walks one page of one channel, so a resumed attempt loses at most
    # a page instead of a whole team. No page url means the channel's first page.
    current_channel: ChannelRef | None = None
    next_messages_url: str | None = None


class TeamsConnector(
    CheckpointedConnectorWithPermSync[TeamsCheckpoint],
    SlimConnectorWithPermSync,
):
    MAX_WORKERS = 10

    def __init__(
        self,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are not necessarily guaranteed to be unique
        teams: list[str] | None = None,
        max_workers: int = MAX_WORKERS,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
    ) -> None:
        if teams is None:
            teams = []
        self.graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self.max_workers = max_workers
        self.requested_team_list: list[str] = teams
        # Channels walked again from their first page in this attempt: a saved
        # page url Graph rejects recovers once per attempt and can never loop.
        self._restarted_channel_ids: set[str] = set()
        # The current channel's readers, read once per channel per attempt. The
        # cache dies with the process, so a resumed attempt re-reads them fresh.
        self._channel_readers: dict[str, _ChannelReaders] = {}

        resolved_env = resolve_microsoft_environment(graph_api_host, authority_host)
        self._azure_environment = resolved_env.environment
        self.authority_host = resolved_env.authority_host
        self.graph_api_host = resolved_env.graph_host

    # impls for BaseConnector

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.msal_app = build_msal_app(
            client_id=credentials["teams_client_id"],
            directory_id=credentials["teams_directory_id"],
            authority_host=self.authority_host,
            client_secret=credentials["teams_client_secret"],
        ).app

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise RuntimeError("MSAL app is not initialized")

            token = acquire_graph_token(self.msal_app, self.graph_api_host)

            if not isinstance(token, dict):
                raise RuntimeError("`token` instance must be of type dict")

            return token

        self.graph_client = GraphClient(
            _acquire_token_func, environment=self._azure_environment
        )
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
                "Requested team count: %s, Has special chars: %s",
                len(self.requested_team_list) if self.requested_team_list else 0,
                has_special_chars,
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
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        checkpoint = copy.deepcopy(checkpoint)

        if checkpoint.todo_team_ids is None:
            teams = _collect_all_teams(
                graph_client=self.graph_client,
                requested=self.requested_team_list,
            )
            checkpoint.todo_team_ids = [team.id for team in teams if team.id]
        elif checkpoint.current_channel is None and not checkpoint.todo_channels:
            # A team is left, or has_more would have ended the walk.
            team_id = checkpoint.todo_team_ids.pop()
            team = _get_team_by_id(graph_client=self.graph_client, team_id=team_id)
            checkpoint.todo_channels = [
                _channel_ref(team_id, channel)
                for channel in _collect_all_channels_from_team(team=team)
            ]
            logger.info(
                "Listed %s channel(s) of team %s; %s team(s) left",
                len(checkpoint.todo_channels),
                team_id,
                len(checkpoint.todo_team_ids),
            )
        else:
            if checkpoint.current_channel is None:
                checkpoint.current_channel = checkpoint.todo_channels.pop()
            yield from _walk_channel_page(
                self.graph_client,
                checkpoint,
                start,
                self._restarted_channel_ids,
                self._channel_readers,
            )

        checkpoint.has_more = bool(
            checkpoint.current_channel
            or checkpoint.todo_channels
            or checkpoint.todo_team_ids
        )
        return checkpoint

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        # Every document already carries its channel's access list, so the plain
        # walk is the permission walk.
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
            graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
            requested=self.requested_team_list,
        )

        for team in teams:
            if not team.id:
                logger.warning(
                    "Expected a team with an id, instead got no id: team=%r", team
                )
                continue

            channels = _collect_all_channels_from_team(
                team=team,
            )

            for channel in channels:
                if not channel.id:
                    logger.warning(
                        "Expected a channel with an id, instead got no id: channel=%r",
                        channel,
                    )
                    continue

                # A refused members call raises: a listing without its readers
                # would let pruning and permission sync act on a partial picture.
                _, external_access = fetch_channel_readers(
                    graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
                    team_id=team.id,
                    channel_id=channel.id,
                )

                messages = fetch_messages(
                    graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
                    team_id=team.id,
                    channel_id=channel.id,
                    start=start,
                )

                slim_doc_buffer: list[SlimDocument | HierarchyNode] = []

                for message in messages:
                    # The indexing walk skips these roots, so listing them here
                    # would keep their stale documents out of pruning.
                    if not message.is_indexable:
                        continue
                    slim_doc_buffer.append(
                        SlimDocument(
                            id=message.id,
                            external_access=external_access,
                            # NOTE: doc_created_at population not yet verified against live data
                            doc_created_at=message.created_date_time,
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


def _sender_name(message: Message) -> str:
    """Bots and apps post without a user, so the sender is not always known."""
    if message.from_ and message.from_.user and message.from_.user.display_name:
        return message.from_.user.display_name
    return "Unknown User"


def _construct_semantic_identifier(channel: ChannelRef, top_message: Message) -> str:
    top_message_user_name = _sender_name(top_message)
    top_message_content = top_message.body.content or ""
    top_message_subject = top_message.subject or "Unknown Subject"
    channel_name = channel.display_name

    try:
        snippet = parse_html_page_basic(top_message_content.rstrip())
        snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet

    except Exception:
        logger.exception(
            "Error parsing snippet for message %s with url %s",
            top_message.id,
            top_message.web_url,
        )
        snippet = ""

    semantic_identifier = (
        f"{top_message_user_name} in {channel_name} about {top_message_subject}"
    )
    if snippet:
        semantic_identifier += f": {snippet}"

    return semantic_identifier


def _message_header(message: Message) -> str:
    return (
        f"From: {_sender_name(message)}\nDate: {message.created_date_time.isoformat()}"
    )


def _message_section(message: Message) -> TextSection | None:
    """One section per message, so a hit cites the message that said it."""
    body = parse_html_page_basic(message.body.content) if message.body.content else ""
    body = body.strip()
    if not body:
        return None
    return TextSection(
        link=message.web_url, text=f"{_message_header(message)}\n\n{body}"
    )


def _modified_at(message: Message) -> datetime:
    return message.last_modified_date_time or message.created_date_time


def _convert_thread_to_document(
    channel: ChannelRef,
    root: Message,
    replies: list[Message],
    expert_infos: list[BasicExpertInfo],
    external_access: ExternalAccess,
) -> Document:
    """A thread (the root message and its replies) is one document, oldest first."""
    messages = sorted([root, *replies], key=lambda m: m.created_date_time)
    sections = [
        section
        for message in messages
        if message.is_indexable and (section := _message_section(message))
    ]
    # The slim walk lists every indexable root, so a thread edited down to no
    # text must still replace its document or the old text would outlive it.
    if not sections:
        sections = [TextSection(link=root.web_url, text=_message_header(root))]

    return Document(
        id=root.id,
        sections=sections,
        source=DocumentSource.TEAMS,
        semantic_identifier=_construct_semantic_identifier(channel, root),
        title="",  # teams threads don't really have a "title"
        doc_created_at=root.created_date_time,
        # Indexing skips a document whose update time has not moved, and an
        # edit or a deleted reply moves a message's modified time, not its creation.
        doc_updated_at=max(_modified_at(message) for message in messages),
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
            "All requested team names contain special characters (&, (, )) which require client-side filtering. Using basic /teams endpoint with pagination. Teams: %s",
            problematic_names,
        )
        # Use unfiltered query with pagination limit to avoid fetching too many teams
        use_client_side_filtering = True
        odata_filter = None
    elif problematic_names and safe_names:
        # Mixed scenario - need to fetch more teams to find the problematic ones
        logger.info(
            "Mixed team types: will use client-side filtering for all. Safe names: %s, Special char names: %s",
            safe_names,
            problematic_names,
        )
        use_client_side_filtering = True
        odata_filter = None
    elif safe_names:
        # All names are safe - use OData filtering
        logger.info("Using OData filtering for all requested teams: %s", safe_names)
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
                query.before_execute(partial(_update_request_url, next_url=url))

            team_collection = execute_query_with_retry(
                query, method_name="_collect_all_teams"
            )
        except (ClientRequestException, ValueError) as e:
            # If OData filter fails, fall back to client-side filtering
            if not use_client_side_filtering and odata_filter:
                logger.warning(
                    "OData filter failed: %s. Falling back to client-side filtering.", e
                )
                use_client_side_filtering = True
                odata_filter = None
                teams = []
                next_url = None
                page_count = 0
                continue
            # If client-side approach also fails, re-raise
            logger.error("Teams query failed: %s", e)
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
                    "Searched %s pages, found %s matching teams so far",
                    page_count,
                    len(found_team_names),
                )

            # Stop if we found all requested teams or hit the page limit
            if requested_set.issubset(found_team_names):
                logger.info("Found all requested teams after %s pages", page_count)
                break
            elif page_count >= max_pages:
                logger.warning(
                    "Reached maximum page limit (%s) while searching for teams. Found: %s, Missing: %s",
                    max_pages,
                    found_team_names & requested_set,
                    requested_set - found_team_names,
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
    query = graph_client.teams.get().filter(f"id eq '{team_id}'").top(1)
    team_collection = execute_query_with_retry(query, method_name="_get_team_by_id")

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

    # `get_all` follows the collection's pages itself.
    query = team.channels.get_all(
        # explicitly needed because of incorrect type definitions provided by the `office365` library
        page_loaded=lambda _: None
    )
    channel_collection = execute_query_with_retry(
        query, method_name="_collect_all_channels_from_team"
    )
    return [channel for channel in channel_collection if channel.id]


def _channel_ref(team_id: str, channel: Channel) -> ChannelRef:
    return ChannelRef(
        team_id=team_id,
        id=channel.id,
        display_name=channel.properties.get("displayName") or "Unknown",
    )


def _status(error: requests.HTTPError) -> int | None:
    return error.response.status_code if error.response is not None else None


def _is_permanent(error: requests.HTTPError) -> bool:
    """A refusal or a missing resource stays that way, so it is recorded and the
    walk moves on. Anything else (expired token, exhausted retries) fails the
    attempt so the saved checkpoint is retried, not skipped for good."""
    return _status(error) in (403, 404)


def _rejects_saved_cursor(
    error: requests.HTTPError,
    checkpoint: TeamsCheckpoint,
    restarted_channel_ids: set[str],
) -> bool:
    """Graph answers a page url it no longer honors with 400 or 410 (measured
    for a tampered skip token). Retrying it would never progress, so the channel
    is walked again from its first page, once per attempt."""
    channel = checkpoint.current_channel
    return (
        channel is not None
        and checkpoint.next_messages_url is not None
        and channel.id not in restarted_channel_ids
        and _status(error) in (400, 410)
    )


_ChannelReaders = tuple[list[BasicExpertInfo], ExternalAccess]


def _leave_channel(
    checkpoint: TeamsCheckpoint, readers_cache: dict[str, _ChannelReaders]
) -> None:
    if checkpoint.current_channel is not None:
        readers_cache.pop(checkpoint.current_channel.id, None)
    checkpoint.current_channel = None
    checkpoint.next_messages_url = None


def _channel_failure(channel: ChannelRef, error: Exception) -> ConnectorFailure:
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=channel.id),
        failure_message=f"Could not read channel {channel.id} of team {channel.team_id}",
        exception=error,
    )


def _walk_channel_page(
    graph_client: GraphClient,
    checkpoint: TeamsCheckpoint,
    start: SecondsSinceUnixEpoch,
    restarted_channel_ids: set[str],
    readers_cache: dict[str, _ChannelReaders],
) -> Iterator[Document | ConnectorFailure]:
    """One page of the current channel's threads. Moves the checkpoint to the
    next page, or off the channel when the page was its last or is refused."""
    channel = checkpoint.current_channel
    if channel is None:
        raise RuntimeError("No channel is being walked")

    # Readers are never checkpointed, a saved list would be stale on resume.
    # Without them the channel cannot be indexed safely, so a refusal is one
    # recorded failure for the channel and the walk moves on.
    try:
        readers = readers_cache.get(channel.id)
        if readers is None:
            readers = fetch_channel_readers(
                graph_client=graph_client,
                team_id=channel.team_id,
                channel_id=channel.id,
            )
            readers_cache[channel.id] = readers
        expert_infos, external_access = readers
    except requests.HTTPError as e:
        if not _is_permanent(e):
            raise
        yield _channel_failure(channel, e)
        _leave_channel(checkpoint, readers_cache)
        return

    try:
        roots, next_url = fetch_message_page(
            graph_client=graph_client,
            request_url=checkpoint.next_messages_url
            or message_delta_url(channel.team_id, channel.id, start),
        )
    except requests.HTTPError as e:
        if _rejects_saved_cursor(e, checkpoint, restarted_channel_ids):
            logger.warning(
                "Graph rejected the saved page of channel %s; walking it again "
                "from its first page",
                channel.id,
            )
            checkpoint.next_messages_url = None
            restarted_channel_ids.add(channel.id)
            return
        if not _is_permanent(e):
            raise
        yield _channel_failure(channel, e)
        _leave_channel(checkpoint, readers_cache)
        return

    for root in roots:
        # A thread is its root message. A deleted or system root drops the
        # whole thread, which is what the slim walk lists for pruning too.
        if not root.is_indexable:
            continue
        try:
            replies = list(
                fetch_replies(
                    graph_client=graph_client,
                    team_id=channel.team_id,
                    channel_id=channel.id,
                    root_message_id=root.id,
                )
            )
        except requests.HTTPError as e:
            if not _is_permanent(e):
                raise
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=root.id),
                failure_message=f"Could not read the replies of {root.id} in channel {channel.id}",
                exception=e,
            )
            continue
        yield _convert_thread_to_document(
            channel=channel,
            root=root,
            replies=replies,
            expert_infos=expert_infos,
            external_access=external_access,
        )

    checkpoint.next_messages_url = next_url
    if next_url is None:
        _leave_channel(checkpoint, readers_cache)


if __name__ == "__main__":
    from tests.daily.connectors.utils import load_all_from_connector

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

    for _slim_doc in teams_connector.retrieve_all_slim_docs_perm_sync():
        ...

    for doc in load_all_from_connector(
        connector=teams_connector,
        start=0.0,
        end=datetime.now(tz=timezone.utc).timestamp(),
    ).documents:
        print(doc)
