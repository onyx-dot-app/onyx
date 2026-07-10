"""Document push — deliver successfully indexed documents to an external endpoint.

This module owns the document push payload shape and the config-driven sink.
There are two delivery mechanisms for the same payload:

- the config-driven sink below, configured entirely through environment
  variables (DOCUMENT_PUSH_ENDPOINT_URL et al.), available in all editions; and
- the EE DOCUMENT_PUSH hook (onyx/hooks/points/document_push.py), managed via
  the /admin/hooks API, which reuses these payload models.

The two sinks are either/or, never both: the call site checks this config
first (a cached local read) and only falls back to the hook when it is unset.

Like the hook, this sink is single-tenant only — a shared destination would
mix documents from different organizations (the payload carries no tenant
identifier).

The endpoint URL is operator-supplied through the environment, so unlike
admin-entered hook URLs it is trusted to point at private-network destinations
— pushing to an internal system is the primary use case. Scheme and structural
validation still apply.

Push failures never fail the indexing batch: failures are logged and swallowed.
"""

from functools import lru_cache

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import DOCUMENT_PUSH_API_KEY
from onyx.configs.app_configs import DOCUMENT_PUSH_ENDPOINT_URL
from onyx.configs.app_configs import DOCUMENT_PUSH_TIMEOUT_SECONDS
from onyx.utils.external_endpoint import ExternalEndpointConfig
from onyx.utils.external_endpoint import post_json_to_endpoint
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url

logger = setup_logger()


class DocumentPushPayload(BaseModel):
    """Payload sent to a document push endpoint after a document is indexed.

    This fires after successful indexing and is fire-and-forget — the response
    is not used to alter the document or pipeline behavior.
    """

    document_id: str = Field(description="Unique identifier for the document.")
    title: str | None = Field(description="Title of the document.")
    content: str = Field(
        description="Full text content of the document (all text sections concatenated)."
    )
    source: str = Field(
        description=(
            "Connector source type (e.g. confluence, slack, google_drive). "
            "Full list: https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/configs/constants.py#L195"
        )
    )
    url: str | None = Field(
        description="Canonical URL of the document at its source, if available."
    )
    doc_updated_at: str | None = Field(
        description="ISO 8601 UTC timestamp of the last update at the source, or null if unknown."
    )
    metadata: dict[str, list[str]] = Field(
        description="Key-value metadata attached to the document. Values are always a list of strings."
    )


class DocumentPushResponse(BaseModel):
    """Response from a Document Push hook endpoint. Exists to satisfy the hook
    framework's type requirements, which demand a JSON object body on 2xx.
    The config-driven sink does not use it — it ignores the body entirely."""


@lru_cache(maxsize=1)
def get_document_push_config() -> ExternalEndpointConfig | None:
    """Build the endpoint config from the environment, or None when unset.

    An invalid URL disables the feature and logs an error (once, via the
    cache) rather than raising — a misconfigured push destination must not
    take down indexing.
    """
    if not DOCUMENT_PUSH_ENDPOINT_URL:
        return None
    try:
        endpoint_url = validate_outbound_http_url(
            DOCUMENT_PUSH_ENDPOINT_URL, allow_private_network=True
        )
    except (SSRFException, ValueError):
        logger.exception(
            "DOCUMENT_PUSH_ENDPOINT_URL is invalid — config-driven document "
            "push is disabled"
        )
        return None
    if DOCUMENT_PUSH_TIMEOUT_SECONDS <= 0:
        logger.error(
            "DOCUMENT_PUSH_TIMEOUT_SECONDS must be positive (got %s) — "
            "config-driven document push is disabled",
            DOCUMENT_PUSH_TIMEOUT_SECONDS,
        )
        return None
    logger.notice(
        "Config-driven document push enabled — pushing indexed documents to %s",
        endpoint_url,
    )
    return ExternalEndpointConfig(
        endpoint_url=endpoint_url,
        api_key=DOCUMENT_PUSH_API_KEY,
        timeout_seconds=DOCUMENT_PUSH_TIMEOUT_SECONDS,
    )


def push_document_via_config(payload: DocumentPushPayload) -> None:
    """POST one indexed document to the configured endpoint.

    No-op when DOCUMENT_PUSH_ENDPOINT_URL is unset. Never raises — this push
    is fire-and-forget and must not affect indexing.
    """
    config = get_document_push_config()
    if config is None:
        return
    try:
        # No response_type: the push is fire-and-forget, so any 2xx counts as
        # success regardless of body (endpoints commonly ACK with 204/empty).
        outcome, _ = post_json_to_endpoint(
            config=config,
            payload=payload.model_dump(),
        )
        if outcome.is_success:
            logger.debug(
                "Pushed document_id=%s (HTTP %s, %sms)",
                payload.document_id,
                outcome.status_code,
                outcome.duration_ms,
            )
        else:
            # The client already logged the failure detail; this line adds the
            # document context the generic client doesn't have.
            logger.warning(
                "Failed to push document_id=%s: %s",
                payload.document_id,
                outcome.error_message,
            )
    except Exception:
        logger.exception(
            "Unexpected error pushing document_id=%s to the configured endpoint",
            payload.document_id,
        )
