"""Capability checks for the Notion connector.

The indexing checks register in ``registry.py``. Notion has no permission sync.
Each check makes small probes (one page, one block, one database row) with the
gateway operations that indexing calls, with ``fast=True``: a rate limit raises
at once and stops the run.

Notion shows an integration only the pages and databases that a user shared
with it. Notion answers 404 for a page that is not shared, the same as for a
page that does not exist. An integration with nothing shared is the most
common failure, so the messages tell the admin how to share pages.

Indexing reads the connector config this way: with a root page ID, it reads
that page and its children. Without one, it reads every page that search
returns.
"""

from typing import Any, NoReturn

from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckNotApplicableError,
    CheckOutput,
    CheckRowText,
    CredentialCapability,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    TimedOutValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.config import NotionConnectorConfig
from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionSourceOperations,
)
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/notion"
_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description=(
        "The check stopped after {time_limit} without an answer from Notion.\n"
        "Re-run the checks."
    ),
)
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Notion")
_ERROR_DETAIL_CHARS = 300
# Keeps a row's line short when it names a page or database.
_TITLE_CHARS = 24
_UNTITLED = "Untitled"

_SHARE_HINT = (
    "In Notion, open each top-level page or database to index, select the "
    "••• menu > Connections, and add the integration. Its child pages are "
    "shared with it too."
)
_CAPABILITIES_HINT = (
    "In Notion, open the integration's settings (Integrations > the "
    "integration > Capabilities)"
)
_READ_CONTENT = "Read content"
_READ_USERS = "Read user information"

_AUTH_CHECK_ID = "notion_auth"
_SHARED_CONTENT_CHECK_ID = "notion_shared_content"
_ROOT_PAGE_CHECK_ID = "notion_root_page"
# check_id to the checks it runs after. The shared-content and root-page
# checks are alternatives: only one applies to a config.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _SHARED_CONTENT_CHECK_ID: (_AUTH_CHECK_ID,),
    _ROOT_PAGE_CHECK_ID: (_AUTH_CHECK_ID,),
    "notion_page_content": (_SHARED_CONTENT_CHECK_ID, _ROOT_PAGE_CHECK_ID),
    "notion_database_rows": (_AUTH_CHECK_ID,),
    "notion_user_info": (_AUTH_CHECK_ID,),
}


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _gateway(context: CapabilityCheckContext) -> NotionSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, NotionSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _root_page_id(config: NotionConnectorConfig) -> str:
    return (config.root_page_id or "").strip()


def _need(capability: str) -> str:
    """The line that says which integration capability a probe needs."""
    return (
        "In Notion, open Integrations > the integration > Capabilities and "
        f"select {capability}."
    )


def _plain_text(rich_text: Any) -> str:
    if not isinstance(rich_text, list):
        return ""
    return "".join(
        str(part.get("plain_text", "")) for part in rich_text if isinstance(part, dict)
    ).strip()


def _title(notion_object: dict[str, Any]) -> str:
    """The short title of a page (its title property) or of a database or
    data source (its ``title``)."""
    title: str = _plain_text(notion_object.get("title"))
    properties: Any = notion_object.get("properties")
    if not title and isinstance(properties, dict):
        title = next(
            (
                _plain_text(prop.get("title"))
                for prop in properties.values()
                if isinstance(prop, dict) and prop.get("type") == "title"
            ),
            "",
        )
    if not title:
        return _UNTITLED
    if len(title) <= _TITLE_CHARS:
        return title
    return title[: _TITLE_CHARS - 1].rstrip() + "…"


def _raise_for_api_error(
    error: NotionApiError,
    *,
    denied: str,
    denied_row: _RowText,
    not_found: str | None = None,
    not_found_row: _RowText | None = None,
    not_found_denies: bool = False,
) -> NoReturn:
    """Maps a Notion API error onto the validation-exception family.
    ``denied`` explains a 403 for this probe, ``not_found`` a 404; the rows
    are what the check's row shows for them. ``not_found_denies`` reads a
    404 as a denial: search returned the object, so it exists."""
    status: int | None = error.status_code
    detail: str = str(error)[:_ERROR_DETAIL_CHARS]
    if error.is_rate_limited:
        raise RateLimitedValidationError(
            "Notion rate limited the check. Run the checks again in a minute.",
            summary="Rate limited by Notion",
            description=(
                "Notion refused the request because of its rate limit. (HTTP 429)\n"
                "Wait a minute, then re-run."
            ),
        ) from error
    if status is None and error.timed_out:
        raise TimedOutValidationError(
            f"Notion did not answer in time: {detail}",
            summary="Timed out",
            description="Notion did not answer the request in time.\nRe-run the checks.",
        ) from error
    if status is None:
        raise UnreachableValidationError(
            f"Onyx cannot connect to the Notion API: {detail}",
            summary="Cannot reach Notion",
            description=(
                "The request to the Notion API failed.\nCheck that the server can "
                "reach api.notion.com."
            ),
        ) from error
    if status == 401:
        raise CredentialExpiredError(
            "Notion rejected the integration token (HTTP 401). The token is wrong, "
            "or the integration was deleted. Copy the integration's current "
            "Internal Integration Secret.",
            summary="Notion rejected the integration token",
            description=(
                "Notion does not accept this token. (HTTP 401)\nIn Notion, open "
                "Integrations > the integration > Configuration and copy the "
                "Internal Integration Secret."
            ),
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(
            f"{denied} (HTTP 403).",
            summary=denied_row.summary,
            description=denied_row.description,
        ) from error
    if status == 404 and not_found is not None and not_found_row is not None:
        error_class: type[ConnectorValidationError] = (
            InsufficientPermissionsError
            if not_found_denies
            else ConnectorValidationError
        )
        raise error_class(
            f"{not_found} (HTTP 404).",
            summary=not_found_row.summary,
            description=not_found_row.description,
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected Notion response (HTTP {status}): {detail}",
        summary="Unexpected response from Notion",
        description=(
            "Notion answered in a way that this check does not know.\nRe-run the "
            "checks."
        ),
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


def _read_content_denied_row(effect: str) -> _RowText:
    return _RowText(
        summary="Integration cannot read content",
        description=(
            f"Without the Read content capability, the integration {effect}. "
            f"(HTTP 403)\n{_need(_READ_CONTENT)}"
        ),
    )


_SEARCH_DENIED_ROW = _read_content_denied_row("finds no page to index")
_PAGE_CONTENT_DENIED_ROW = _RowText(
    summary="Integration cannot read page content",
    description=f"Indexed pages would have no text. (HTTP 403)\n{_need(_READ_CONTENT)}",
)


class _NotionCheck(CapabilityCheck[NotionConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        fails_when_unreachable: bool = False,
        timeout_text: CheckRowText = _TIMEOUT_TEXT,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            required=required,
            requires_connector_instance=False,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=timeout_text,
        )


def _signed_in_line(bot_user: dict[str, Any]) -> str:
    name: str = str(bot_user.get("name") or "the integration")
    bot: Any = bot_user.get("bot")
    workspace: Any = bot.get("workspace_name") if isinstance(bot, dict) else None
    return (
        f"Signed in as {name} in {workspace}" if workspace else f"Signed in as {name}"
    )


class _AuthCheck(_NotionCheck):
    """Reads the token's bot user, as indexing does to name the workspace."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_AUTH_CHECK_ID,
            display_name="Sign in to Notion",
            remediation=(
                "Copy the Internal Integration Secret from the integration's "
                "settings in Notion (Integrations > the integration > "
                "Configuration) and update the credential."
            ),
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            bot_user: dict[str, Any] = _gateway(context).get_bot_user(fast=True)
        except ConnectorMissingCredentialError as e:
            raise CredentialInvalidError(
                "The credential has no Notion integration token.",
                summary="Account has no integration token",
                description=(
                    "The account has no Notion integration token.\nPaste the "
                    "Internal Integration Secret into the Notion Integration "
                    "Token field of the account."
                ),
            ) from e
        except NotionApiError as e:
            if e.status_code is None and e.timed_out:
                raise TimedOutValidationError(
                    f"Notion did not answer the sign-in in time: {e}",
                    summary=_SIGN_IN_TIMEOUT_TEXT.summary,
                    description=_SIGN_IN_TIMEOUT_TEXT.description,
                ) from e
            _raise_for_api_error(
                e,
                denied="Notion does not let the integration read its bot user",
                denied_row=_RowText(
                    summary="Integration cannot read its bot user",
                    description=(
                        "Notion refused to describe the integration. (HTTP 403)\n"
                        "In Notion, open Integrations > the integration > "
                        "Capabilities and check its settings."
                    ),
                ),
            )
        return CheckOutput(summary=_signed_in_line(bot_user))


class _SharedContentCheck(_NotionCheck):
    """Search returns what indexing reads when no root page is set."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=_SHARED_CONTENT_CHECK_ID,
            display_name="Find shared pages",
            remediation=_SHARE_HINT,
        )

    def applies(self, form_state: FormState[NotionConnectorConfig]) -> bool:
        return not _root_page_id(form_state.config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: NotionSourceOperations = _gateway(context)
        try:
            page: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.PAGE
            )
            if page is not None:
                return CheckOutput(summary=f"Found shared page {_title(page)}")
            data_source: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.DATA_SOURCE
            )
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=_content_denied("search the workspace"),
                denied_row=_SEARCH_DENIED_ROW,
            )
        if data_source is not None:
            return CheckOutput(summary=f"Found shared database {_title(data_source)}")
        raise InsufficientPermissionsError(
            "No page or database is shared with the integration, so there is "
            f"nothing to index. {_SHARE_HINT}",
            summary="No pages shared with the integration",
            description=(
                "Notion shows an integration only the pages shared with it.\nIn "
                "Notion, open each top-level page or database to index and add "
                "the integration under ••• > Connections."
            ),
        )


class _RootPageCheck(_NotionCheck):
    """Reads the root page as indexing does: a page, else a database (a page
    that became a wiki is a database). A run without a config has no root
    page: indexing then reads every shared page, which the shared-content
    check tests."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=_ROOT_PAGE_CHECK_ID,
            display_name="Find root page",
            remediation=(
                "Use the 32-character ID at the end of the page URL. Then share the "
                "page with the integration: open the page, select the ••• menu > "
                "Connections, and add the integration."
            ),
        )

    def applies(self, form_state: FormState[NotionConnectorConfig]) -> bool:
        # An empty root page ID means "every shared page", not a missing value.
        return bool(_root_page_id(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        root_page_id: str = _root_page_id(self.config(context))
        if not root_page_id:
            raise CheckNotApplicableError("No root page is set.")
        gateway: NotionSourceOperations = _gateway(context)
        try:
            page: dict[str, Any] = gateway.get_page(page_id=root_page_id, fast=True)
            return CheckOutput(summary=f"Read root page {_title(page)}")
        except NotionApiError as e:
            if e.status_code != 404:
                self._raise(e, root_page_id)
        try:
            database: dict[str, Any] = gateway.get_database(
                database_id=root_page_id, fast=True
            )
        except NotionApiError as e:
            self._raise(e, root_page_id)
        return CheckOutput(summary=f"Read root page {_title(database)}")

    def _raise(self, error: NotionApiError, root_page_id: str) -> NoReturn:
        if error.status_code == 400:
            raise ConnectorValidationError(
                f"`{root_page_id}` is not a valid Notion page ID (HTTP 400): "
                f"{str(error)[:_ERROR_DETAIL_CHARS]}",
                summary="Root page ID is not valid",
                description=(
                    "Notion rejected the ID format. (HTTP 400)\nEnter the "
                    "32-character ID from the end of the page URL in the Root "
                    "Page ID field."
                ),
            ) from error
        _raise_for_api_error(
            error,
            denied=_content_denied(f"read the root page `{root_page_id}`"),
            denied_row=_read_content_denied_row("cannot read the root page"),
            not_found=(
                f"Notion found no page with the ID `{root_page_id}` that is shared "
                "with the integration. Check the ID, and share the page with the "
                "integration (••• menu > Connections)"
            ),
            not_found_row=_RowText(
                summary="Root page not found or not shared",
                description=(
                    "Notion answers the same for a missing page and an unshared "
                    "one. (HTTP 404)\nCheck the ID, and add the integration to the "
                    "page under ••• > Connections."
                ),
            ),
        )


class _PageContentCheck(_NotionCheck):
    """Reads the blocks of one page: a page from search, else the root page."""

    config_class = NotionConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_page_content",
            display_name="Sample page content",
            remediation=(
                f"{_CAPABILITIES_HINT} and select 'Read content'. Then share the "
                "pages to index with the integration."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: NotionSourceOperations = _gateway(context)
        root_page_id: str = _root_page_id(self.config(context))
        try:
            page: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.PAGE
            )
            has_databases: bool = (
                page is None
                and not root_page_id
                and _first_search_result(gateway, NotionSearchObjectType.DATA_SOURCE)
                is not None
            )
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=_content_denied("search the workspace"),
                denied_row=_SEARCH_DENIED_ROW,
            )
        if page is not None:
            return self._read_searched_page(gateway, page)
        if root_page_id:
            return self._read_root_page(gateway, root_page_id)
        # A database row is a page, so search finds no page only when every
        # shared database is empty.
        raise NothingToCheckError(
            "No page is shared with the integration, so there is no page content "
            "to read.",
            summary="No pages in scope",
            description=(
                "Only databases with no rows are shared."
                if has_databases
                else "No page or database is shared with the integration."
            ),
        )

    def _read_searched_page(
        self, gateway: NotionSourceOperations, page: dict[str, Any]
    ) -> CheckOutput:
        page_id: str = str(page["id"])
        try:
            gateway.get_block_children(block_id=page_id, page_size=1, fast=True)
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=_content_denied("read page content"),
                denied_row=_PAGE_CONTENT_DENIED_ROW,
                not_found=(
                    f"Search returned the page `{page_id}`, but Notion does not let "
                    "the integration read its content"
                ),
                not_found_row=_RowText(
                    summary="Page found but content unreadable",
                    description=(
                        "Indexed pages would have no text. (HTTP 404)\nSelect Read "
                        "content in the integration's capabilities."
                    ),
                ),
                not_found_denies=True,
            )
        return CheckOutput(summary=f"Read content of {_title(page)}")

    def _read_root_page(
        self, gateway: NotionSourceOperations, root_page_id: str
    ) -> CheckOutput:
        try:
            gateway.get_block_children(block_id=root_page_id, page_size=1, fast=True)
        except NotionApiError as e:
            if e.status_code not in (400, 404):
                _raise_for_api_error(
                    e,
                    denied=_content_denied("read page content"),
                    denied_row=_PAGE_CONTENT_DENIED_ROW,
                )
            # notion_root_page reports a root page that is not readable; a
            # wiki root is a database, which has no blocks.
            raise InconclusiveValidationError(
                "Search returned no page, and Notion cannot read the blocks of the "
                f"root page `{root_page_id}`: {str(e)[:_ERROR_DETAIL_CHARS]}",
                summary="No page content to sample",
                description=(
                    "Search returned no page, and the root page has no blocks to "
                    f"read. (HTTP {e.status_code})\nShare a page under the root "
                    "page with the integration, then re-run."
                ),
            ) from e
        return CheckOutput(summary="Read content of the root page")


class _DatabaseRowsCheck(_NotionCheck):
    """Reads one row of one shared database, as indexing does: the database
    lists its data sources, and each data source is queried for its rows."""

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_database_rows",
            display_name="Sample database rows",
            required=False,
            remediation=(
                "Share the databases to index with the integration (••• menu > "
                f"Connections). {_CAPABILITIES_HINT} and select 'Read content'."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: NotionSourceOperations = _gateway(context)
        try:
            data_source: dict[str, Any] | None = _first_search_result(
                gateway, NotionSearchObjectType.DATA_SOURCE
            )
            if data_source is None:
                raise NothingToCheckError(
                    "No database is shared with the integration, so there is no "
                    "database row to read.",
                    summary="No database shared to test",
                    description="No database is shared with the integration.",
                )
            parent: Any = data_source.get("parent") or {}
            database_id: Any = parent.get("database_id")
            if database_id:
                gateway.get_database(database_id=str(database_id), fast=True)
            rows: dict[str, Any] = gateway.query_data_source(
                data_source_id=str(data_source["id"]), page_size=1, fast=True
            )
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=_content_denied("read database rows")
                + ". Indexing skips the rows of databases it cannot read",
                denied_row=_RowText(
                    summary="Integration cannot read database rows",
                    description=(
                        "Indexing skips the rows of databases it cannot read. (HTTP "
                        f"403)\n{_need(_READ_CONTENT)}"
                    ),
                ),
                not_found=(
                    "Notion found the database in search but does not let the "
                    "integration read it. Share the database with the integration "
                    "(••• menu > Connections)"
                ),
                not_found_row=_RowText(
                    summary="Database found but not readable",
                    description=(
                        "Indexing would skip the database's rows. (HTTP 404)\nAdd "
                        "the integration to the database under ••• > Connections."
                    ),
                ),
                not_found_denies=True,
            )
        title: str = _title(data_source)
        if rows.get("results"):
            return CheckOutput(summary=f"Read a row of {title}")
        return CheckOutput(
            summary=f"Queried {title}",
            advisories=[
                CheckAdvisory(
                    message=(
                        f"The database {title} has no rows, so no row was read. "
                        "Notion answered the query, so the integration can read "
                        "its rows."
                    )
                )
            ],
        )


class _UserInfoCheck(_NotionCheck):
    """Reads one page of users. Indexing writes the names of people
    properties (for example Assignee) into the document text. It reads no
    email."""

    def __init__(self) -> None:
        super().__init__(
            check_id="notion_user_info",
            display_name="Read user names",
            required=False,
            remediation=(
                f"{_CAPABILITIES_HINT} and select 'Read user information without "
                "email addresses'. Onyx does not need email addresses."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            users: dict[str, Any] = _gateway(context).list_users(fast=True)
        except NotionApiError as e:
            _raise_for_api_error(
                e,
                denied=(
                    "The integration cannot read user information, so people "
                    "properties (for example Assignee) index without names. "
                    f"{_CAPABILITIES_HINT} and select 'Read user information "
                    "without email addresses'"
                ),
                denied_row=_RowText(
                    summary="Integration cannot read user names",
                    description=(
                        "People properties, such as Assignee, index without names. "
                        f"(HTTP 403)\n{_need(_READ_USERS)}"
                    ),
                ),
            )
        results: Any = users.get("results")
        count: int = len(results) if isinstance(results, list) else 0
        shown: str = f"{count}+" if users.get("has_more") else str(count)
        noun: str = "user" if shown == "1" else "users"
        return CheckOutput(summary=f"Names readable for {shown} {noun}")


def build_notion_indexing_checks() -> list[CapabilityCheck]:
    return [
        _AuthCheck(),
        _SharedContentCheck(),
        _RootPageCheck(),
        _PageContentCheck(),
        _DatabaseRowsCheck(),
        _UserInfoCheck(),
    ]
