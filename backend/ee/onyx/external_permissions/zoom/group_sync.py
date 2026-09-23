"""Who is in "everyone at <domain>" for a recording shared under a domain
sign-in rule: the Zoom account's own roster, bucketed by email domain. The
listing shows active users only, so a deactivated or still-pending user drops
out at the next sync. Every roster domain gets a group, named by a rule or
not. A wildcard in a rule is read as a shell pattern over the roster domains,
so "*.example.com" takes the subdomains and not example.com itself.
"""

from collections import defaultdict
from collections.abc import Generator
from fnmatch import fnmatchcase

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.utils import credential_json
from onyx.access.utils import build_domain_group_id
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.zoom.client import MAX_LISTING_PAGES, ZoomClient
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.recordings.models import ZoomListingIncomplete
from onyx.connectors.zoom.recordings.recording_access import (
    load_rule_grants,
    usable_emails,
)
from onyx.db.models import ConnectorCredentialPair


def zoom_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = ZoomConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(credential_json(cc_pair))
    if connector.client is None:
        raise ConnectorMissingCredentialError("Zoom")
    yield from domain_groups(connector.client)


def domain_groups(client: ZoomClient) -> Generator[ExternalUserGroup, None, None]:
    emails, any_user_id = account_roster(client)
    members_by_domain: dict[str, set[str]] = defaultdict(set)
    for email in emails:
        _, at, domain = email.rpartition("@")
        if at and domain:
            members_by_domain[domain].add(email)
    # Read before anything is yielded, so a refused catalogue fails the attempt
    # with no group half-written.
    patterns = sorted(wildcard_rule_domains(client, any_user_id))

    # A roster domain matches only itself, so one pass serves both.
    for name in [*sorted(members_by_domain), *patterns]:
        members = sorted(
            email
            for domain, addresses in members_by_domain.items()
            if fnmatchcase(domain, name)
            for email in addresses
        )
        if members:
            yield ExternalUserGroup(id=build_domain_group_id(name), user_emails=members)


def wildcard_rule_domains(client: ZoomClient, user_id: str | None) -> set[str]:
    return {
        domain
        for grant in load_rule_grants(client, user_id).values()
        for domain in grant.domains
        if "*" in domain
    }


def account_roster(client: ZoomClient) -> tuple[set[str], str | None]:
    """Every usable email in the account, and any user id, which the rule
    catalogue is read through. Raises rather than returning a listing Zoom cut
    short: a group filled from part of the roster would revoke access for
    everyone left out, and a failed attempt at least shows up as one."""
    emails: list[str] = []
    any_user_id: str | None = None
    expected: int | None = None
    page_token: str | None = None
    seen_tokens: set[str] = set()
    for _ in range(MAX_LISTING_PAGES):
        page = client.list_users(page_token=page_token)
        emails.extend(user.email for user in page.users)
        any_user_id = any_user_id or next((u.id for u in page.users if u.id), None)
        if expected is None:
            expected = page.total_records

        page_token = page.next_page_token
        if not page_token:
            if expected is None:
                raise ZoomListingIncomplete(
                    "Zoom sent no total_records for the account's users, so the "
                    "listing cannot be checked for users it left out"
                )
            if len(emails) < expected:
                raise ZoomListingIncomplete(
                    f"Zoom listed {len(emails)} of the {expected} users it reported"
                )
            return usable_emails("the account's users", emails), any_user_id
        if page_token in seen_tokens:
            raise ZoomListingIncomplete("Zoom stopped advancing the users cursor")
        seen_tokens.add(page_token)

    raise ZoomListingIncomplete(
        f"Zoom kept paging the account's users past {MAX_LISTING_PAGES} pages"
    )
