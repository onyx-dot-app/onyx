"""The Slack cloud that every Slack feature in Onyx talks to.

Commercial Slack runs on slack.com. GovSlack, Slack's FedRAMP cloud, runs on
slack-gov.com. One deployment uses one cloud, set by SLACK_API_URL. All Slack
hosts (Web API, OAuth, file upload, workspace links) come from that cloud, so
nothing can mix the two.
"""

import os
import re
from urllib.parse import urlparse

from onyx.utils.logger import setup_logger

logger = setup_logger()

_COMMERCIAL_DOMAIN = "slack.com"
# Only these clouds can receive a Slack token. Any other host is rejected, so a
# bad value cannot send a token to an unknown server.
_TRUSTED_SLACK_DOMAINS = frozenset({_COMMERCIAL_DOMAIN, "slack-gov.com"})


def _load_slack_domain() -> str:
    raw = (os.environ.get("SLACK_API_URL") or "").strip()
    if not raw:
        return _COMMERCIAL_DOMAIN
    try:
        parsed = urlparse(raw)
        scheme, hostname = parsed.scheme, parsed.hostname
    except ValueError:
        scheme, hostname = "", None
    if scheme != "https" or hostname not in _TRUSTED_SLACK_DOMAINS:
        logger.error(
            "Ignoring SLACK_API_URL=%r: expected https on one of %s. "
            "Falling back to %s.",
            raw,
            sorted(_TRUSTED_SLACK_DOMAINS),
            _COMMERCIAL_DOMAIN,
        )
        return _COMMERCIAL_DOMAIN
    return hostname


# The Slack cloud domain: "slack.com" or "slack-gov.com".
SLACK_DOMAIN = _load_slack_domain()
# Web API base, for example https://slack-gov.com/api/. Socket Mode follows it,
# because the SDK opens the socket with apps.connections.open on this base.
SLACK_API_URL = f"https://{SLACK_DOMAIN}/api/"
SLACK_OAUTH_AUTHORIZE_URL = f"https://{SLACK_DOMAIN}/oauth/v2/authorize"
SLACK_OAUTH_ACCESS_URL = f"{SLACK_API_URL}oauth.v2.access"
# Host for the pre-signed URLs from files.getUploadURLExternal.
SLACK_FILES_HOST = f"files.{SLACK_DOMAIN}"
# Where admins create the Slack app.
SLACK_APPS_URL = f"https://api.{SLACK_DOMAIN}/apps"

_ESCAPED_DOMAIN = re.escape(SLACK_DOMAIN)


def is_slack_host(netloc: str) -> bool:
    """True for the configured cloud's domain or any of its subdomains, such
    as a workspace host like acme.slack-gov.com."""
    host = netloc.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    return host == SLACK_DOMAIN or host.endswith(f".{SLACK_DOMAIN}")


def slack_url_pattern(path_pattern: str) -> str:
    """An egress regex for the configured cloud's Web API, for example
    https://slack-gov\\.com/api/.*"""
    return f"https://{_ESCAPED_DOMAIN}{path_pattern}"


def slack_files_url_pattern(path_pattern: str) -> str:
    """An egress regex for the configured cloud's file-upload host."""
    return f"https://files\\.{_ESCAPED_DOMAIN}{path_pattern}"
