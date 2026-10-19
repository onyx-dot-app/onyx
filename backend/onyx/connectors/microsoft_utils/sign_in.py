"""The sign-in probe every Microsoft connector's first check runs: one
app-only token request, mapped onto the sign-in row."""

from collections.abc import Callable

from onyx.connectors.microsoft_utils.check_text import (
    sign_in_text,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    raise_for_auth_error,
    raise_for_sign_in_error,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftSignIn,
    MicrosoftTokenInfo,
)


def sign_in(
    check_token: Callable[[], MicrosoftTokenInfo], labels: MicrosoftAccountLabels
) -> MicrosoftSignIn:
    """Signs in with ``check_token`` and returns the passing row's text.
    Raises the validation family with the sign-in row's text."""
    try:
        token: MicrosoftTokenInfo = check_token()
    except MicrosoftAuthError as error:
        raise_for_auth_error(error, labels)
    except MicrosoftGraphError as error:
        raise_for_sign_in_error(error)
    return sign_in_text(token, labels)
