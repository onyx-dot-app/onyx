"""
Utility to validate and block disposable/temporary email addresses.

This module fetches a list of known disposable email domains from a remote source
and caches them for performance. It's used during user registration to prevent
abuse from temporary email services.
"""

import httpx

from onyx.auth.domain_blocklist import RemoteDomainBlocklist
from onyx.configs.app_configs import DISPOSABLE_EMAIL_DOMAINS_URL

# Hardcoded fallback list of common disposable domains
# This ensures we block at least these even if the remote fetch fails
FALLBACK_DISPOSABLE_DOMAINS = frozenset(
    {
        "trashlify.com",
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "tempmail.com",
        "chat-tempmail.com",
        "throwaway.email",
        "yopmail.com",
        "temp-mail.org",
        "getnada.com",
        "maildrop.cc",
    }
)


def _parse_json_list(response: httpx.Response) -> set[str]:
    """The list is a JSON array of domains."""
    domains_list = response.json()
    if not isinstance(domains_list, list):
        raise ValueError(f"Expected a JSON list of domains, got {type(domains_list)}")
    return {domain.lower().strip() for domain in domains_list if domain}


def disposable_domain_blocklist() -> RemoteDomainBlocklist:
    """A new, empty cache of the disposable-domain list."""
    return RemoteDomainBlocklist(
        name="disposable email",
        url=DISPOSABLE_EMAIL_DOMAINS_URL,
        fallback_domains=FALLBACK_DISPOSABLE_DOMAINS,
        parse=_parse_json_list,
    )


# The one instance the app uses. Python imports a module once per process, so
# this runs once and every caller of `is_disposable_email` shares the same
# cache and refresh thread. That makes it a singleton per process without a
# `__new__` guard: nothing in the app calls the factory a second time. Each
# API or Celery worker process has its own instance, as it would with any
# in-memory cache. Tests call the factory directly to get a fresh, empty cache.
_blocklist = disposable_domain_blocklist()


def is_disposable_email(email: str) -> bool:
    """
    Check if an email address uses a disposable/temporary domain.

    Args:
        email: The email address to check

    Returns:
        True if the email uses a disposable domain, False otherwise
    """
    return _blocklist.contains_email_domain(email)


def refresh_disposable_domains() -> None:
    """
    Force a refresh of the disposable domains list.

    This can be called manually if you want to update the list
    without waiting for the cache to expire. Unlike normal cache
    expiry, this blocks until the refresh completes.
    """
    _blocklist.refresh_now()
