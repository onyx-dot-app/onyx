"""How a refused Graph or SharePoint call is judged and worded. A refusal that
stays (403, 404) is recorded and the walk moves on, anything else fails the
attempt so it is retried."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import requests
from office365.runtime.client_request_exception import ClientRequestException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorFailure, EntityFailure
from onyx.connectors.teams.models import ChannelRef
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def warn_group_left_out(channel: ChannelRef, call: str, error: Exception) -> None:
    """The group sync deletes the groups a failed run did not reach, so raising
    on one refused channel would take access from every team listed after it.
    Left out, the refusal costs the one group, which fails closed."""
    logger.warning(
        'The %s of channel "%s" in team %s could not be read, so its group is '
        "left out of this sync: %s",
        call,
        channel.display_name,
        channel.team_id,
        error,
    )


def _error_body(error: requests.HTTPError) -> dict[str, Any]:
    """Graph's error object, empty when the body is not one."""
    if error.response is None:
        return {}
    try:
        payload = error.response.json()
    except ValueError:
        return {}
    body = payload.get("error") if isinstance(payload, dict) else None
    return body if isinstance(body, dict) else {}


def graph_inner_error_code(error: requests.HTTPError) -> str:
    """Graph's inner error code, or its outer code, or the empty string. The
    inner one comes first: it names the cause, where the outer one repeats the
    status."""
    body = _error_body(error)
    inner = body.get("innerError")
    if isinstance(inner, dict) and inner.get("code"):
        return str(inner["code"])
    return str(body.get("code") or "")


def graph_error_message(error: requests.HTTPError) -> str:
    return str(_error_body(error).get("message") or "")


def graph_said(error: requests.HTTPError) -> str:
    """Graph's own code and message. A refusal the connector cannot name is
    otherwise unreadable, and a missing grant is only its most common cause."""
    return (
        f"Graph said: {graph_inner_error_code(error) or 'no code'}, "
        f"{graph_error_message(error) or 'no message'}"
    )
