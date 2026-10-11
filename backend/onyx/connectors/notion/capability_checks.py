"""Capability checks for the Notion connector.

Each check composes the gateway operations the indexing path itself uses,
searching at page size one, so a passing check proves the exact calls a run
will make. Checks need no connector instance: the runner constructs the
registered ``NotionSourceOperations`` gateway from the credential, so every
check but the root-page one also runs at credential-creation time.

Notion internal integrations have no OAuth scopes, only per-integration
capabilities. Read access rests on two facts: the integration has the Read
content capability, and a workspace member has shared the page, database or
wiki with it. Notion answers 404 for content that exists but is not shared, so
the remediation text for a 404 names sharing, and the text for a 403 names the
capability.

Permission-sync checks are not registered here: they live in EE beside the
censor.
"""

from typing import Any, NoReturn

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.config import NotionConnectorConfig
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionGatewayError,
    NotionSourceOperations,
)
from onyx.connectors.source_operations import SourceOperations

_NOTION_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/notion"

_SHARE_REMEDIATION = (
    "In Notion open the page or database, choose the `...` menu, then "
    "Connections, and add the integration. Child pages inherit the share."
)
_CAPABILITY_HINT = (
    "Enable `Read content` under Capabilities on the integration's page at "
    "notion.so/profile/integrations."
)

# One result proves the permission. More only spends the rate limit.
_PROBE_PAGE_SIZE = 1

_PAGE_SEARCH: dict[str, Any] = {
    "filter": {"property": "object", "value": "page"},
    "page_size": _PROBE_PAGE_SIZE,
}
_DATA_SOURCE_SEARCH: dict[str, Any] = {
    "filter": {"property": "object", "value": "data_source"},
    "page_size": _PROBE_PAGE_SIZE,
}
_PAGE_SEARCH_DENIED = "The integration cannot search pages"

# A page id that Notion will not serve as a page: malformed, unshared, or a
# wiki, which the API models as a database.
_NOT_A_PAGE_STATUSES = frozenset({400, 404})


# Everything a probe can raise that maps onto a validation outcome.
_PROBE_ERRORS = (NotionGatewayError, ConnectorMissingCredentialError)


def _gateway(context: CapabilityCheckContext) -> NotionSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, NotionSourceOperations):
        raise RuntimeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _raise_for_notion_error(e: Exception, denied_message: str) -> NoReturn:
    """Maps a probe error onto the validation-exception family.

    ``denied_message`` explains what the integration could not reach; it is
    used for the deterministic answers (400, 403, 404).
    """
    if isinstance(e, ConnectorMissingCredentialError):
        raise CredentialInvalidError(
            "Notion credential is missing the `notion_integration_token` field."
        ) from e
    if not isinstance(e, NotionApiError):
        raise UnexpectedValidationError(f"Notion could not be reached: {e}") from e
    if e.status_code == 400:
        raise ConnectorValidationError(
            f"{denied_message}: Notion rejected the request (HTTP 400). Check "
            "the configured ids."
        ) from e
    if e.status_code == 401:
        raise CredentialExpiredError(
            "Notion rejected the integration token (HTTP 401). The secret is "
            "wrong or rotated, or the integration was deleted."
        ) from e
    if e.status_code == 403:
        raise InsufficientPermissionsError(
            f"{denied_message} (HTTP 403). {_CAPABILITY_HINT}"
        ) from e
    if e.status_code == 404:
        raise ConnectorValidationError(
            f"{denied_message} (HTTP 404, which Notion also answers for content "
            "that is not shared with the integration)."
        ) from e
    if e.status_code == 429:
        raise UnexpectedValidationError(
            "Notion rate-limited the probe (HTTP 429). Try again in a minute."
        ) from e
    raise UnexpectedValidationError(
        f"Notion returned HTTP {e.status_code}: {e.body}"
    ) from e


def _search(
    gateway: NotionSourceOperations, query: dict[str, Any], denied_message: str
) -> list[dict[str, Any]]:
    try:
        return gateway.search(query=query)["results"]
    except _PROBE_ERRORS as e:
        _raise_for_notion_error(e, denied_message)


def _first_shared_page(gateway: NotionSourceOperations) -> dict[str, Any] | None:
    results: list[dict[str, Any]] = _search(gateway, _PAGE_SEARCH, _PAGE_SEARCH_DENIED)
    return results[0] if results else None


class _TokenAuthCheck(CapabilityCheck):
    """Reads the integration's own bot user, the cheapest authenticated call."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="notion_token_auth",
            display_name="Integration token is valid",
            requires_connector_instance=False,
            remediation=(
                "Paste the Internal Integration Secret from the integration's "
                "page at notion.so/profile/integrations."
            ),
            docs_link=_NOTION_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).get_bot_user()
        except _PROBE_ERRORS as e:
            _raise_for_notion_error(e, "The integration cannot read its own user")


class _SharedPagesCheck(CapabilityCheck[NotionConnectorConfig]):
    """Searches for one page: an integration nobody has shared with sees
    nothing, and indexing would produce no documents. With a root page
    configured, indexing reads that page directly and the root-page check
    covers it, since search can miss pages."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="notion_shared_pages",
            display_name="Pages are shared with the integration",
            requires_connector_instance=False,
            remediation=_SHARE_REMEDIATION,
            docs_link=_NOTION_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        if self.config(context).root_page_id:
            return
        if _first_shared_page(_gateway(context)) is None:
            raise ConnectorValidationError(
                "No page is shared with the integration, so there is nothing to index."
            )


class _RootPageCheck(CapabilityCheck[NotionConnectorConfig]):
    """Fetches the configured root page. A 400 or 404 retries it as a
    database: a page turned into a wiki is a database to the API."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="notion_root_page",
            display_name="Root page is readable",
            requires_connector_instance=False,
            requires_fields=frozenset({"root_page_id"}),
            remediation=(
                "Check the root page id (the 32 hex characters after the title "
                "in the page URL, before any `?`) and share that page with the "
                "integration. " + _SHARE_REMEDIATION
            ),
            docs_link=_NOTION_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        root_page_id: str | None = self.config(context).root_page_id
        if root_page_id is None:
            raise RuntimeError("Bug: the runner guarantees requires_fields.")
        gateway: NotionSourceOperations = _gateway(context)
        denied: str = f"The integration cannot read the root page `{root_page_id}`"
        try:
            gateway.get_page(page_id=root_page_id)
            return
        except _PROBE_ERRORS as e:
            if not (
                isinstance(e, NotionApiError) and e.status_code in _NOT_A_PAGE_STATUSES
            ):
                _raise_for_notion_error(e, denied)
        try:
            gateway.get_database(database_id=root_page_id)
        except _PROBE_ERRORS as e:
            _raise_for_notion_error(e, denied)


class _PageContentCheck(CapabilityCheck[NotionConnectorConfig]):
    """Reads the page indexing will start from: the configured root's child
    blocks, or for a search-driven connector the first shared page's object
    (the call recursive child-page indexing makes) and child blocks."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="notion_page_content",
            display_name="Page content is readable",
            requires_connector_instance=False,
            remediation=_SHARE_REMEDIATION,
            docs_link=_NOTION_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: NotionSourceOperations = _gateway(context)
        root_page_id: str | None = self.config(context).root_page_id
        if root_page_id:
            try:
                gateway.list_block_children(block_id=root_page_id)
            except _PROBE_ERRORS as e:
                _raise_for_notion_error(
                    e,
                    f"The integration cannot read the blocks of the root page "
                    f"`{root_page_id}`",
                )
            return
        page: dict[str, Any] | None = _first_shared_page(gateway)
        if page is None:
            # The shared-pages check reports this, so there is nothing to read.
            return
        page_id: str = page["id"]
        try:
            gateway.get_page(page_id=page_id)
            gateway.list_block_children(block_id=page_id)
        except _PROBE_ERRORS as e:
            _raise_for_notion_error(
                e, f"The integration cannot read the page `{page_id}`"
            )


class _DatabaseQueryCheck(CapabilityCheck):
    """Reads one shared database and queries its data source.

    Not required: indexing logs and skips a database it cannot query, so the
    connector still works, with that database's pages missing.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="notion_database_query",
            display_name="Databases can be queried",
            required=False,
            requires_connector_instance=False,
            remediation=_SHARE_REMEDIATION,
            docs_link=_NOTION_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: NotionSourceOperations = _gateway(context)
        results: list[dict[str, Any]] = _search(
            gateway,
            _DATA_SOURCE_SEARCH,
            "The integration cannot search databases",
        )
        if not results:
            # No database is shared, so there is nothing to query.
            return
        data_source_id: str = results[0]["id"]
        database_id: str = results[0]["parent"]["database_id"]
        try:
            gateway.get_database(database_id=database_id)
            gateway.query_data_source(data_source_id=data_source_id)
        except _PROBE_ERRORS as e:
            _raise_for_notion_error(
                e,
                "The integration cannot query the shared database "
                f"`{database_id}`, so its pages are skipped during indexing",
            )


def build_notion_indexing_checks() -> list[CapabilityCheck]:
    """Returns the INDEXING capability checks for Notion."""
    return [
        _TokenAuthCheck(),
        _SharedPagesCheck(),
        _RootPageCheck(),
        _PageContentCheck(),
        _DatabaseQueryCheck(),
    ]
