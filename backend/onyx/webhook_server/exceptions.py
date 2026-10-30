"""What a source's verifier and parser raise.

Separate from `OnyxError` so a source writes no HTTP: the route decides the
status code, and a source that raised one of these cannot accidentally leak
why a delivery was rejected.
"""


class WebhookAuthError(Exception):
    """The delivery did not prove it came from the source."""


class WebhookPayloadError(Exception):
    """The body is this source's, but it cannot be read."""
