"""What a source's verifier and parser raise. Not `OnyxError`: the route
picks the status code, so a source cannot leak why it rejected a delivery."""


class WebhookAuthError(Exception):
    """The delivery did not prove it came from the source."""


class WebhookPayloadError(Exception):
    """The body is this source's, but it cannot be read."""
