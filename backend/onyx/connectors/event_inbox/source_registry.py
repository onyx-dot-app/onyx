"""The webhook view of the event sources in `registration`."""

from onyx.configs.app_configs import WEBHOOK_PUBLIC_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookSourceSpec
from onyx.connectors.event_inbox.registration import (
    get_event_source,
    get_event_source_by_slug,
    registered_event_sources,
)


def get_webhook_source(slug: str) -> WebhookSourceSpec | None:
    record = get_event_source_by_slug(slug)
    return record.webhook if record is not None else None


def registered_webhook_sources() -> list[WebhookSourceSpec]:
    return [record.webhook for record in registered_event_sources()]


def webhook_source_for(source: DocumentSource) -> WebhookSourceSpec | None:
    record = get_event_source(source)
    return record.webhook if record is not None else None


def webhook_callback_url(slug: str, endpoint: str = "") -> str:
    """The URL an admin registers with the provider."""
    return f"{WEBHOOK_PUBLIC_URL.rstrip('/')}/webhook/{slug}{endpoint}"
