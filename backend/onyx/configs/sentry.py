from typing import Any

from sentry_sdk.types import Event

from onyx.utils.logger import setup_logger

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

    _instance_id_resolved = True

    try:
        import sentry_sdk

        from onyx.utils.telemetry import get_or_generate_uuid

        instance_id = get_or_generate_uuid()
        sentry_sdk.set_tag("instance_id", instance_id)

        # Also set on this event since set_tag won't retroactively apply
        event.setdefault("tags", {})["instance_id"] = instance_id
    except Exception:
        logger.debug("Failed to resolve instance_id for Sentry tagging")

    return event
