"""Which source owns which webhook endpoint."""

from onyx.configs.app_configs import WEBHOOK_PUBLIC_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookSourceSpec

_SPECS: dict[str, WebhookSourceSpec] = {}


def register_webhook_source(spec: WebhookSourceSpec) -> None:
    """Expose one source's endpoint at import time. Refuses a clash rather
    than moving a live URL."""
    existing = _SPECS.get(spec.slug)
    if existing is not None and existing is not spec:
        raise ValueError(
            f"Webhook slug {spec.slug} is already registered to "
            f"{existing.source.value}."
        )

    claimed = webhook_source_for(spec.source)
    if claimed is not None and claimed.slug != spec.slug:
        raise ValueError(
            f"{spec.source.value} already receives events at "
            f"{claimed.slug}; a source has one endpoint."
        )

    _SPECS[spec.slug] = spec


def unregister_webhook_source(slug: str) -> None:
    """For the loader's rollback and for tests. Ignores an unknown slug."""
    _SPECS.pop(slug, None)


def get_webhook_source(slug: str) -> WebhookSourceSpec | None:
    return _SPECS.get(slug)


def registered_webhook_sources() -> list[WebhookSourceSpec]:
    return sorted(_SPECS.values(), key=lambda spec: spec.slug)


def webhook_callback_url(slug: str, endpoint: str = "") -> str:
    """The URL an admin registers with the provider."""
    return f"{WEBHOOK_PUBLIC_URL.rstrip('/')}/webhook/{slug}{endpoint}"


def webhook_source_for(source: DocumentSource) -> WebhookSourceSpec | None:
    for spec in _SPECS.values():
        if spec.source == source:
            return spec
    return None
