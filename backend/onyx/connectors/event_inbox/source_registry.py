"""Which source owns which endpoint.

A source registers one `WebhookSourceSpec`; the webhook server and the drain
both build from this registry. It mirrors `connectors/registry.py`, which maps
a source to its connector class, so the two seams read the same way.
"""

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookSourceSpec

_SPECS: dict[str, WebhookSourceSpec] = {}


def register_webhook_source(spec: WebhookSourceSpec) -> None:
    """Expose one source's endpoint. Import-time; the route list is fixed
    once the app is built.

    Refuses a duplicate rather than replacing it. A slug is a live URL and a
    source resolves to one spec, so a clash means two modules disagree about
    which owns it; taking the last would move an endpoint, or leave
    `get_webhook_source` and `webhook_source_for` answering differently.
    """
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
    """Give up a slug. Unknown slugs are ignored.

    Registration is an import side effect, so the only callers are the ones
    that undo it: the loader rolling back a failed import, and tests.
    """
    _SPECS.pop(slug, None)


def get_webhook_source(slug: str) -> WebhookSourceSpec | None:
    return _SPECS.get(slug)


def registered_webhook_sources() -> list[WebhookSourceSpec]:
    return sorted(_SPECS.values(), key=lambda spec: spec.slug)


def webhook_callback_url(slug: str) -> str:
    """The URL an admin registers with the provider.

    Built from WEB_DOMAIN because every deployment fronts the webhook server
    at /webhook on the same host: the Helm nginx and ingress route it there,
    and so does the Compose nginx.
    """
    return f"{WEB_DOMAIN.rstrip('/')}/webhook/{slug}"


def webhook_source_for(source: DocumentSource) -> WebhookSourceSpec | None:
    """The spec a source registered, if it receives pushed events."""
    for spec in _SPECS.values():
        if spec.source == source:
            return spec
    return None
