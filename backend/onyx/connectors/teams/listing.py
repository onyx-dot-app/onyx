"""Which teams and channels a run covers: the teams the admin named, or every
team of the tenant, and the channels of each."""

from functools import partial

from office365.graph_client import GraphClient
from office365.runtime.client_request_exception import ClientRequestException
from office365.runtime.http.request_options import RequestOptions
from office365.runtime.queries.client_query import ClientQuery
from office365.teams.channels.channel import Channel
from office365.teams.team import Team

from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.utils import escape_odata_string, execute_query_with_retry
from onyx.utils.logger import setup_logger

logger = setup_logger()


def has_odata_incompatible_chars(team_names: list[str] | None) -> bool:
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
        escaped_name = escape_odata_string(name)
        filter_parts.append(f"displayName eq '{escaped_name}'")

    return " or ".join(filter_parts)


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


def _team_page_query(
    graph_client: GraphClient, odata_filter: str | None, next_url: str | None
) -> ClientQuery:
    """One page of the teams listing: filtered by name, or 50 plain rows."""
    if odata_filter is None:
        query = graph_client.teams.get().top(50)
    else:
        # Graph accepts only 'eq' operators in this filter.
        query = graph_client.teams.get().filter(odata_filter)
    # Works around a Graph issue with ampersands in filters.
    query.before_execute(lambda req: _add_prefer_header(request=req))
    if next_url:
        query.before_execute(partial(_update_request_url, next_url=next_url))
    return query


def collect_all_teams(
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

    # No names means every team, which is what the connector form promises, so
    # the plain listing is paged to its end with no name to stop on.
    every_team = not requested
    _, safe_names, problematic_names = _can_use_odata_filter(requested)

    # Determine filtering strategy based on Microsoft Graph limitations
    if every_team:
        logger.info("No teams configured, listing every team")
        use_client_side_filtering = True
        odata_filter = None
    elif problematic_names and not safe_names:
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
    else:
        # All names are safe - use OData filtering
        logger.info("Using OData filtering for all requested teams: %s", safe_names)
        use_client_side_filtering = False
        odata_filter = _build_simple_odata_filter(safe_names)

    # Track pagination to avoid fetching too many teams for client-side filtering
    max_pages = 200
    page_count = 0

    while True:
        try:
            team_collection = execute_query_with_retry(
                partial(
                    _team_page_query,
                    graph_client,
                    None if use_client_side_filtering else odata_filter,
                    next_url,
                ),
                method_name="collect_all_teams",
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
        if use_client_side_filtering and not every_team:
            page_count += 1
            found_team_names = {
                team.display_name for team in teams if team.display_name
            }
            requested_set = set(requested or [])

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
        # Listing every team has no name to stop on, so a page that points back
        # at itself would be read for ever.
        if team_collection._next_request_url == next_url:
            raise RuntimeError(f"Graph repeated a page of teams: {next_url}")

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


def get_team_by_id(
    graph_client: GraphClient,
    team_id: str,
) -> Team:
    team_collection = execute_query_with_retry(
        lambda: graph_client.teams.get().filter(f"id eq '{team_id}'").top(1),
        method_name="get_team_by_id",
    )

    if not team_collection:
        raise ValueError(f"No team with {team_id=} was found")
    elif team_collection.has_next:
        # shouldn't happen, but catching it regardless
        raise RuntimeError(f"Multiple teams with {team_id=} were found")

    return team_collection[0]


def collect_all_channels_from_team(
    team: Team,
) -> list[Channel]:
    if not team.id:
        raise RuntimeError(f"The {team=} has an empty `id` field")

    # `get_all` follows the collection's pages itself. The argument is needed
    # because of incorrect type definitions in the `office365` library.
    channel_collection = execute_query_with_retry(
        lambda: team.channels.get_all(page_loaded=lambda _: None),
        method_name="collect_all_channels_from_team",
    )
    return [channel for channel in channel_collection if channel.id]


def channel_ref(team_id: str, channel: Channel) -> ChannelRef:
    return ChannelRef(
        team_id=team_id,
        id=channel.id,
        display_name=channel.properties.get("displayName") or "Unknown",
        membership_type=channel.properties.get("membershipType"),
    )
