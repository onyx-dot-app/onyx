import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.outbound_fields import OutboundField, OutboundUrlField
from onyx.server.security.models import web_connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.url import SSRFException, validate_outbound_http_url

_DNS_LABEL = re.compile(r"[a-z0-9-]{1,63}")


def validate_connector_url(url: str, field: str, *, https_only: bool = False) -> str:
    """Raises ``ConnectorValidationError`` if a connector would reach internal
    infrastructure through ``url``. Uses the web connector's SSRF level rule:
    at the default level only public hosts are reachable; at a relaxed level
    private hosts are reachable but cloud metadata stays blocked."""
    enforced: bool = web_connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    try:
        _ = urlsplit(url.strip()).port
        return validate_outbound_http_url(
            url,
            https_only=https_only,
            allow_private_network=not enforced,
            block_link_local_only=not enforced,
        )
    except (SSRFException, ValueError) as e:
        raise ConnectorValidationError(f"Invalid {field}: {e}") from e


def validate_dns_label(value: str, field: str) -> str:
    """Raises ``ConnectorValidationError`` unless ``value`` is one DNS label, so
    it cannot change the host of a ``https://{value}.vendor.com`` URL."""
    if not _DNS_LABEL.fullmatch(value):
        raise ConnectorValidationError(
            f"Invalid {field}: use only letters, digits and hyphens"
        )
    return value


def _vendor_label(value: str, vendor_domain: str) -> str:
    cleaned = value.strip().lower().rstrip("/")
    cleaned = cleaned.removeprefix("https://").removeprefix("http://")
    return cleaned.split(f".{vendor_domain}")[0]


def validate_outbound_fields(
    fields: Iterable[OutboundField], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Validates each declared field that ``values`` sets. Returns ``values``
    with each vendor subdomain cut down to the label that was checked, so the
    connector cannot build a different host from the raw value."""
    checked = dict(values)
    for field in fields:
        value = values.get(field.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise ConnectorValidationError(f"Invalid {field.key}: must be a string")
        if isinstance(field, OutboundUrlField):
            url = value.strip()
            validate_connector_url(url if "://" in url else f"https://{url}", field.key)
        else:
            checked[field.key] = validate_dns_label(
                _vendor_label(value, field.vendor_domain), field.key
            )
    return checked
