"""Capability checks for the Notion connector.

The indexing checks register in ``registry.py``. Notion has no permission sync.
Each check makes small probes (one page, one block, one database row) with the
gateway operations that indexing calls, with ``fast=True``: a rate limit raises
at once and maps to INDETERMINATE.

Notion shows an integration only the pages and databases that a user shared
with it. Notion answers 404 for a page that is not shared, the same as for a
page that does not exist. An integration with nothing shared is the most
common failure, so the messages tell the admin how to share pages.

Indexing reads the connector config this way: with a root page ID, it reads
that page and its children. Without one, it reads every page that search
returns.
"""

from typing import Any, NoReturn

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.notion.config import NotionConnectorConfig
from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionSourceOperations,
)
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/notion"
_ERROR_DETAIL_CHARS = 300

_SHARE_HINT = (
    "In Notion, open each top-level page or database to index, select the "
    "••• menu > Connections, and add the integration. Its child pages are "
    "shared with it too."
)
_CAPABILITIES_HINT = (
    "In Notion, open the integration's settings (Integrations > the "
    "integration > Capabilities)"
)


def _gateway(context: CapabilityCheckContext) -> NotionSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, NotionSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _root_page_id(config: NotionConnectorConfig) -> str:
    return (config.root_page_id or "").strip()


def _raise_for_api_error(
    error: NotionApiError,
    *,
    denied: str,
    not_found: str | None = None,
    bad_request: str | None = None,
) -> NoReturn:
    """Maps a Notion API error onto the validation-exception family.
    ``denied`` explains a 403 for this probe."""
    status: int | None = error.status_code
    detail: str = str(error)[:_ERROR_DETAIL_CHARS]
    if error.is_rate_limited:
        raise UnexpectedValidationError(
            "Notion rate limited the check. Run the checks again in a minute."
        ) from error
    if status is None:
        raise UnexpectedValidationError(
            f"Onyx cannot connect to the Notion API: {detail}"
        ) from error
    if status == 401:
        raise CredentialExpiredError(
            "Notion rejected the integration token (HTTP 401). The token is wrong, "
            "or the integration was deleted. Copy the integration's current "
            "Internal Integration Secret."
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(f"{denied} (HTTP 403).") from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(f"{not_found} (HTTP 404).") from error
    if status == 400 and bad_request is not None:
        raise ConnectorValidationError(f"{bad_request} (HTTP 400): {detail}") from error
    raise UnexpectedValidationError(
        f"Unexpected Notion response (HTTP {status}): {detail}"
    ) from error


def _first_search_result(
    gateway: NotionSourceOperations, object_type: NotionSearchObjectType
) -> dict[str, Any] | None:
    """The first object of this type that search returns, or None. Raises
    ``NotionApiError``."""
    page: NotionSearchResponse | None = next(
        gateway.iter_search(object_type=object_type, page_size=1, fast=True), None
    )
    if page is None or not page.results:
        return None
    return page.results[0]


def _content_denied(what: str) -> str:
    return (
        f"The integration cannot {what}. {_CAPABILITIES_HINT} and select 'Read content'"
    )


class _NotionCheck(CapabilityCheck[NotionConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        requires_connector_config: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            remediation=remediation,
            docs_link=_DOCS_LINK,
        )


class _AuthCheck(_NotionCheck):
    """Reads the token's bot user, as indexing does to name the workspace."""

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_auth",
            display_name="Integration token is valid",
            remediation=(
                "Copy the Internal Integration Secret from the integration's "
                "settings in Notion (Integrations > the integration > "
                "Configuration) and update the credential."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).get_bot_user(fast=True)
        except NotionApiError as e:
            _raise_for_api_error(
                e, denied="Notion does not let the integration read its bot user"
            )


class _SharedContentCheck(_NotionCheck):
    """Search returns what indexing reads when no root page is set."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_shared_content",
            display_name="Pages are shared with the integration",
            remediation=_SHARE_HINT,
        )

    def applies(self, form_state: FormState[NotionConnectorConfig]) -> bool:
        return not _root_page_id(form_state.config)

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: NotionSourceOperations = _gateway(context)
        try:
            found: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.PAGE
            ) or _first_search_result(gateway, NotionSearchObjectType.DATA_SOURCE)
        except NotionApiError as e:
            _raise_for_api_error(e, denied=_content_denied("search the workspace"))
        if found is None:
            raise InsufficientPermissionsError(
                "No page or database is shared with the integration, so there is "
                f"nothing to index. {_SHARE_HINT}"
            )


class _RootPageCheck(_NotionCheck):
    """Reads the root page as indexing does: a page, else a database (a page
    that became a wiki is a database)."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_root_page",
            display_name="Root page is shared with the integration",
            # A credential-time run has no config, so no root page to read.
            requires_connector_config=True,
            remediation=(
                "Use the 32-character ID at the end of the page URL. Then share the "
                "page with the integration: open the page, select the ••• menu > "
                "Connections, and add the integration."
            ),
        )

    def applies(self, form_state: FormState[NotionConnectorConfig]) -> bool:
        # An empty root page ID means "every shared page", not a missing value.
        return bool(_root_page_id(form_state.config))

    def run(self, context: CapabilityCheckContext) -> None:
        root_page_id: str = _root_page_id(self.config(context))
        gateway: NotionSourceOperations = _gateway(context)
        try:
            gateway.get_page(page_id=root_page_id, fast=True)
            return
        except NotionApiError as e:
            if e.status_code != 404:
                self._raise(e, root_page_id)
        try:
            gateway.get_database(database_id=root_page_id, fast=True)
        except NotionApiError as e:
            self._raise(e, root_page_id)

    def _raise(self, error: NotionApiError, root_page_id: str) -> NoReturn:
        _raise_for_api_error(
            error,
            denied=_content_denied(f"read the root page `{root_page_id}`"),
            not_found=(
                f"Notion found no page with the ID `{root_page_id}` that is shared "
                "with the integration. Check the ID, and share the page with the "
                "integration (••• menu > Connections)"
            ),
            bad_request=f"`{root_page_id}` is not a valid Notion page ID",
        )


class _PageContentCheck(_NotionCheck):
    """Reads the blocks of one page: a page from search, else the root page."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_page_content",
            display_name="Page content is readable",
            remediation=(
                f"{_CAPABILITIES_HINT} and select 'Read content'. Then share the "
                "pages to index with the integration."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: NotionSourceOperations = _gateway(context)
        try:
            page: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.PAGE
            )
        except NotionApiError as e:
            _raise_for_api_error(e, denied=_content_denied("search the workspace"))
        page_id: str = (
            str(page["id"]) if page is not None else _root_page_id(self.config(context))
        )
        if not page_id:
            try:
                has_databases: bool = (
                    _first_search_result(gateway, NotionSearchObjectType.DATA_SOURCE)
                    is not None
                )
            except NotionApiError as e:
                _raise_for_api_error(e, denied=_content_denied("search the workspace"))
            if has_databases:
                # Only empty databases are shared: there is no page content to
                # read, and notion_database_rows reads the databases.
                return
            # notion_shared_content reports an integration with nothing shared.
            raise UnexpectedValidationError(
                "No page is shared with the integration, so Onyx cannot verify "
                f"that page content is readable. {_SHARE_HINT}"
            )
        try:
            gateway.get_block_children(block_id=page_id, page_size=1, fast=True)
        except NotionApiError as e:
            if page is None and e.status_code in (400, 404):
                # notion_root_page reports a root page that is not readable.
                raise UnexpectedValidationError(
                    f"Notion cannot read the root page `{page_id}`, so this check "
                    "cannot run. Fix the root page first: "
                    f"{str(e)[:_ERROR_DETAIL_CHARS]}"
                ) from e
            _raise_for_api_error(
                e,
                denied=_content_denied("read page content"),
                not_found=(
                    f"Search returned the page `{page_id}`, but Notion does not let "
                    "the integration read its content"
                ),
            )


class _DatabaseRowsCheck(_NotionCheck):
    """Reads one row of one shared database, as indexing does: the database
    lists its data sources, and each data source is queried for its rows."""

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_database_rows",
            display_name="Database rows are readable",
            required=False,
            remediation=(
                "Share the databases to index with the integration (••• menu > "
                f"Connections). {_CAPABILITIES_HINT} and select 'Read content'."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: NotionSourceOperations = _gateway(context)
        denied: str = _content_denied("read database rows") + (
            ". Indexing skips the rows of databases it cannot read"
        )
        try:
            data_source: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.DATA_SOURCE
            )
            if data_source is None:
                # No database is shared: nothing to read.
                return
            parent: Any = data_source.get("parent") or {}
            database_id: Any = parent.get("database_id")
            if database_id:
                gateway.get_database(database_id=str(database_id), fast=True)
            gateway.query_data_source(
                data_source_id=str(data_source["id"]), page_size=1, fast=True
            )
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=denied,
                not_found=(
                    "Notion found the database in search but does not let the "
                    "integration read it. Share the database with the integration "
                    "(••• menu > Connections)"
                ),
            )


class _UserInfoCheck(_NotionCheck):
    """Reads one user. Indexing writes the names of people properties (for
    example Assignee) into the document text. It reads no email."""

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_user_info",
            display_name="User names are readable",
            required=False,
            remediation=(
                f"{_CAPABILITIES_HINT} and select 'Read user information without "
                "email addresses'. Onyx does not need email addresses."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).list_users(page_size=1, fast=True)
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=(
                    "The integration cannot read user information, so people "
                    "properties (for example Assignee) index without names. "
                    f"{_CAPABILITIES_HINT} and select 'Read user information "
                    "without email addresses'"
                ),
            )


def build_notion_indexing_checks() -> list[CapabilityCheck]:
    return [
        _AuthCheck(),
        _SharedContentCheck(),
        _RootPageCheck(),
        _PageContentCheck(),
        _DatabaseRowsCheck(),
        _UserInfoCheck(),
    ]
