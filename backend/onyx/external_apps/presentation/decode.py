from typing import Any

from onyx.external_apps.presentation.payload_decoders import PayloadDecoder
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.utils.logger import setup_logger

logger = setup_logger()

# action_type namespaces its provider, so entries can't collide.
_DECODERS: dict[str, PayloadDecoder] = {
    action_type: decoder
    for provider in PROVIDERS.values()
    for action_type, decoder in provider.payload_decoders().items()
}


def decode_payload(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Human-readable view of ``payload`` for ``action_type``.

    Fails open to ``payload`` (no decoder, or a decoder that raises) so the
    approval is never blanked or broken.
    """
    decoder = _DECODERS.get(action_type)
    if decoder is None:
        return payload
    try:
        return decoder.decode(payload)
    except Exception:
        logger.exception("payload_decode_failed action_type=%s", action_type)
        return payload
