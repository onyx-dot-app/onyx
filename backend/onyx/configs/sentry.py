from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from sentry_sdk.scrubber import DEFAULT_DENYLIST
from sentry_sdk.scrubber import EventScrubber
from sentry_sdk.types import Event

from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from sentry_sdk.integrations import Integration

logger = setup_logger()

_instance_id_resolved = False


def _add_instance_tags(
    event: Event,
    hint: dict[str, Any],  # noqa: ARG001
) -> Event | None:
    """Sentry before_send hook that lazily attaches instance identification tags.

    On the first event, resolves the instance UUID from the KV store (requires DB)
    and sets it as a global Sentry tag. Subsequent events pick it up automatically.
    """
    global _instance_id_resolved

    if _instance_id_resolved:
        return event

    try:
        import sentry_sdk

        from shared_configs.configs import MULTI_TENANT

        if MULTI_TENANT:
            instance_id = "multi-tenant-cloud"
        else:
            from onyx.utils.telemetry import get_or_generate_uuid

            instance_id = get_or_generate_uuid()

        sentry_sdk.set_tag("instance_id", instance_id)

        # Also set on this event since set_tag won't retroactively apply
        event.setdefault("tags", {})["instance_id"] = instance_id

        # Only mark resolved after success — if DB wasn't ready, retry next event
        _instance_id_resolved = True
    except Exception:
        logger.debug("Failed to resolve instance_id for Sentry tagging")

    return event


# Provider API keys ride in litellm's outbound request `headers` dict, which
# Sentry can capture. Its default denylist only has the underscore `x_api_key`,
# so the real hyphenated header names slip through — add them here.
_EXTRA_CREDENTIAL_DENYLIST = [
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "proxy-authorization",
    "anthropic-api-key",
]


def build_event_scrubber() -> EventScrubber:
    """Recursive credential scrubber shared by every Sentry init.

    ``recursive=True`` so a sensitive key nested under a non-sensitive parent
    (e.g. ``headers.x-api-key``) is redacted — the default scrubber only
    inspects top-level keys.
    """
    return EventScrubber(
        denylist=DEFAULT_DENYLIST + _EXTRA_CREDENTIAL_DENYLIST,
        recursive=True,
    )


def init_sentry(
    *,
    traces_sample_rate: float,
    integrations: list[Integration] | None = None,
) -> None:
    """Initialize Sentry with credential-safe defaults for every entrypoint.

    Routing all inits through here keeps the hardening correct-by-construction:
    no entrypoint can reintroduce the credential leak. Callers guard on
    SENTRY_DSN and pass only what differs (sample rate, integrations).
    """
    import sentry_sdk

    from onyx import __version__
    from shared_configs.configs import SENTRY_DSN

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=integrations or [],
        traces_sample_rate=traces_sample_rate,
        release=__version__,
        before_send=_add_instance_tags,
        # Never capture stack-frame locals: litellm holds the provider key in
        # the outbound request `headers` dict Sentry would otherwise store.
        # Also scrub nested credential keys (incl. the hyphenated x-api-key).
        include_local_variables=False,
        send_default_pii=False,
        event_scrubber=build_event_scrubber(),
    )
    logger.info("Sentry initialized")
