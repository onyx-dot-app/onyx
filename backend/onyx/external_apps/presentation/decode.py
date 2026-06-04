from typing import Any

from onyx.db.models import ExternalApp
from onyx.external_apps.providers.registry import get_provider_for_app
from onyx.utils.logger import setup_logger

logger = setup_logger()


def decode_action_payload(
    app: ExternalApp, action_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Human-readable view of ``payload`` for ``action_type``.

    Resolves the provider's decoder and applies it. Fails open to the original
    ``payload`` (no decoder, or a decoder that raises) so the gate is never
    blanked or broken.
    """
    provider = get_provider_for_app(app)
    if provider is None:
        return payload
    decoder = provider.payload_decoder(action_type)
    if decoder is None:
        return payload
    try:
        return decoder.decode(payload)
    except Exception:
        logger.exception(
            "payload_decode_failed app_type=%s action_type=%s",
            app.app_type,
            action_type,
        )
        return payload
