"""How a refused Graph or SharePoint call is judged and worded. A refusal that
stays (403, 404) is recorded and the walk moves on, anything else fails the
attempt so it is retried."""

from collections.abc import Iterator
from contextlib import contextmanager

import requests
from office365.runtime.client_request_exception import ClientRequestException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorFailure, EntityFailure
from onyx.connectors.teams.models import ChannelRef


def status(error: requests.RequestException) -> int | None:
    return error.response.status_code if error.response is not None else None


def is_permanent(error: requests.RequestException) -> bool:
    """A refusal or a missing resource stays that way, so it is recorded and the
    walk moves on. Anything else (expired token, exhausted retries) fails the
    attempt so the saved checkpoint is retried, not skipped for good."""
    return status(error) in (403, 404)


@contextmanager
def channel_context(channel: ChannelRef, call: str) -> Iterator[None]:
    """A refusal in here stops a walk whose partial listing would delete
    documents, so it becomes an error naming the channel, the call and the way
    out. A transient refusal passes through and the attempt retries it."""
    try:
        yield
    except (requests.HTTPError, ClientRequestException) as e:
        if not is_permanent(e):
            raise
        raise ConnectorValidationError(
            f"{channel_refusal(channel, call, e)} {channel_remedy(call, e)}"
        ) from e


def channel_refusal(
    channel: ChannelRef, call: str, error: requests.RequestException
) -> str:
    """Names the channel and the call, since a channel id alone sends the admin
    looking through Graph for the team and tab it belongs to."""
    return (
        f'The {call} of channel "{channel.display_name}" in team '
        f"{channel.team_id} answered {status(error)}."
    )


# The calls whose grant this connector already names to the admin.
GRANT_BY_CALL = {
    "files folder": "Files.Read.All or Sites.Read.All",
    "files": "Files.Read.All or Sites.Read.All",
}


def channel_remedy(call: str, error: requests.RequestException) -> str:
    """404 is a channel that is gone or invisible to the app, 403 is a grant."""
    if status(error) == 404:
        return "Leave the team out of the connector if the channel is gone."
    grant = GRANT_BY_CALL.get(call, "the application permission that call needs")
    return f"Grant {grant}, or leave the team out of the connector."


def channel_failure(
    channel: ChannelRef, call: str, error: Exception
) -> ConnectorFailure:
    """One channel recorded and skipped. Graph answered with a status for a
    refusal, and with a body this connector cannot use for anything else."""
    named = f'the {call} of channel "{channel.display_name}" in team {channel.team_id}'
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=channel.id),
        failure_message=(
            channel_refusal(channel, call, error)
            if isinstance(error, requests.RequestException)
            else f"Could not read {named}: {error}"
        ),
        exception=error,
    )
