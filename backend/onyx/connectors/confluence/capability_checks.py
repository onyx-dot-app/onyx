"""Capability checks for the Confluence connector.

Each check composes the gateway operations that indexing calls, with small
probes (limit 1, or the first in-scope item). The gateway reaches the site
through the bound config fields (``wiki_base``, ``is_cloud``, ``scoped_token``),
so every check requires ``wiki_base`` and ``is_cloud``. On the create form the
checks wait for the site URL, and config-less credential-time runs skip them.

The indexing scope follows the connector's precedence (``get_indexing_mode``):
CQL query, then page id, then space, then everything. The mode fields are not
``requires_fields``: a blank or absent mode field means "not this mode", so the
mode checks use ``applies`` instead.

OAuth tokens carry the scopes in ``ee/onyx/server/oauth/confluence_cloud.py``.
API tokens and personal access tokens act as their user, so they need that
user's Confluence permissions.
"""

import re
from collections.abc import Iterator
from typing import Any, NoReturn

import requests
from requests import HTTPError

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.confluence.config import ConfluenceConnectorConfig
from onyx.connectors.confluence.connector import (
    ATTACHMENT_EXPANSION_FIELDS,
    COMMENT_EXPANSION_FIELDS,
    PRUNING_EXPANSION_FIELDS,
    ConfluenceIndexingMode,
    build_attachment_cql,
    build_base_page_cql,
    build_comment_cql,
    build_label_filter,
    build_page_cql,
    build_page_retrieval_url,
    get_indexing_mode,
)
from onyx.connectors.confluence.source_operations import (
    OAUTH_REFRESH_TOKEN_KEY,
    ConfluenceNoVisibleSpacesError,
    ConfluenceProbeVariant,
    ConfluenceRetriesExhaustedError,
    ConfluenceSearchVariant,
    ConfluenceSourceOperations,
    ConfluenceSpaceNotFoundError,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/confluence"
_SITE_FIELDS = frozenset({"wiki_base", "is_cloud"})

# Pages sampled when a probe needs a page with attachments.
_SAMPLE_PAGES = 5
_SAMPLE_ATTACHMENTS = 25
# The attachment probe downloads one file; larger files only prove the listing.
_MAX_PROBE_DOWNLOAD_BYTES = 5 * 1024 * 1024
_ERROR_DETAIL_CHARS = 300

_TENANT_INFO_PATH = "/_edge/tenant_info"
_RATE_LIMITED_STATUS = 429
# Results of the CQL query whose content types the CQL check inspects.
_CQL_SAMPLE_RESULTS = 5
_PAGE_TYPE = "page"

_LAST_MODIFIED_PATTERN = re.compile(r"\blastmodified\b", re.IGNORECASE)
_ORDER_BY_PATTERN = re.compile(r"\border\s+by\b", re.IGNORECASE)
# A quoted CQL value; a backslash escapes the next character.
_QUOTED_PATTERN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")


def _gateway(context: CapabilityCheckContext) -> ConfluenceSourceOperations:
    gateway = context.source_operations
    if not isinstance(gateway, ConfluenceSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _mode(config: ConfluenceConnectorConfig) -> ConfluenceIndexingMode:
    return get_indexing_mode(
        space=config.space, page_id=config.page_id, cql_query=config.cql_query
    )


def _label_filter(config: ConfluenceConnectorConfig) -> str:
    return build_label_filter(config.labels_to_skip)


def _scope_cql(config: ConfluenceConnectorConfig) -> str:
    """The page query of an indexing run, without time filters."""
    return build_page_cql(
        build_base_page_cql(
            space=config.space,
            page_id=config.page_id,
            index_recursively=config.index_recursively,
            cql_query=config.cql_query,
        ),
        _label_filter(config),
    )


def _access_hint(
    context: CapabilityCheckContext,
    config: ConfluenceConnectorConfig,
    *,
    oauth_scope: str,
    user_permission: str,
    scoped_token_scope: str | None = None,
) -> str:
    """What to grant, in the terms of the credential type.
    ``scoped_token_scope`` is for an operation whose API differs between OAuth
    and scoped tokens; it defaults to ``oauth_scope``."""
    if OAUTH_REFRESH_TOKEN_KEY in context.credential_json:
        return (
            f"The OAuth token needs the `{oauth_scope}` scope. Connect Confluence "
            "again and accept every scope Onyx asks for."
        )
    if config.scoped_token:
        return (
            f"The scoped API token needs the `{scoped_token_scope or oauth_scope}` "
            "scope. Create a token with the read scopes in the Onyx Confluence "
            "docs."
        )
    return f"The token acts as its Confluence user. Give that user {user_permission}."


def _error_detail(error: HTTPError) -> str:
    response = error.response
    if response is None:
        return str(error)[:_ERROR_DETAIL_CHARS]
    try:
        body = response.json()
    except ValueError:
        body = None
    message = body.get("message") if isinstance(body, dict) else None
    return str(message or response.reason or error)[:_ERROR_DETAIL_CHARS]


def _raise_for_http_error(
    error: HTTPError,
    *,
    denied: str,
    not_found: str | None = None,
    bad_request: str | None = None,
) -> NoReturn:
    """Maps a Confluence HTTP error onto the validation-exception family.
    ``denied`` explains a 403 for this probe."""
    status = error.response.status_code if error.response is not None else None
    detail = _error_detail(error)
    if status == 401:
        raise CredentialExpiredError(
            "Confluence rejected the credential (HTTP 401). The token is wrong, "
            "expired, or revoked, or the email does not match the token."
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(f"{denied} (HTTP 403).") from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(f"{not_found} (HTTP 404).") from error
    if status == 400 and bad_request is not None:
        raise ConnectorValidationError(f"{bad_request} (HTTP 400): {detail}") from error
    if status == 429:
        raise UnexpectedValidationError(
            "Confluence rate limited the check. Run the checks again in a minute."
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected Confluence response (HTTP {status}): {detail}"
    ) from error


def _raise_for_sample_error(error: HTTPError, *, denied: str) -> NoReturn:
    """Like ``_raise_for_http_error``, for a probe that first samples in-scope
    pages. A rejected scope query is the scope checks' failure, not this one."""
    if error.response is not None and error.response.status_code == 400:
        raise UnexpectedValidationError(
            "Confluence rejected the indexing scope query, so this check cannot "
            "run. Fix the scope settings first."
        ) from error
    _raise_for_http_error(error, denied=denied)


def _take(items: Iterator[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    taken: list[dict[str, Any]] = []
    for _ in range(count):
        item = next(items, None)
        if item is None:
            break
        taken.append(item)
    return taken


def _sample_pages(
    context: CapabilityCheckContext,
    config: ConfluenceConnectorConfig,
    expand: str,
) -> Iterator[dict[str, Any]]:
    """In-scope pages with their content, as indexing reads them."""
    return _gateway(context).search_pages(
        variant=ConfluenceSearchVariant.CONTENT,
        cql=_scope_cql(config),
        expand=expand,
        limit=_SAMPLE_PAGES,
    )


class _ConfluenceCheck(CapabilityCheck[ConfluenceConnectorConfig]):
    config_class = ConfluenceConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            required=required,
            requires_connector_instance=False,
            requires_fields=_SITE_FIELDS,
            remediation=remediation,
            docs_link=_DOCS_LINK,
        )


class _SiteAuthCheck(_ConfluenceCheck):
    """Signs in to the site the way the connector does (``probe_site``).

    One check per token type: a scoped API token resolves the cloud id
    (``tenant_info``) and reads through ``api.atlassian.com``; other tokens
    read the site URL.
    """

    def __init__(self, *, scoped: bool) -> None:
        self._scoped = scoped
        if scoped:
            super().__init__(
                check_id="confluence_scoped_token_auth",
                display_name="Scoped API token signs in to the site",
                remediation=(
                    "Scoped API tokens work only with Confluence Cloud. Check the "
                    "site URL, and create a new scoped token if it expired."
                ),
            )
        else:
            super().__init__(
                check_id="confluence_auth",
                display_name="Credential signs in to the site",
                remediation=(
                    "Check the site URL and the Cloud setting. For an API token, "
                    "use the email of the token's Atlassian account. Create a new "
                    "token if it expired. For a scoped API token, turn on "
                    "'Using scoped token'."
                ),
            )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return form_state.config.scoped_token == self._scoped

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            _gateway(context).probe_site(
                variant=(
                    ConfluenceProbeVariant.SCOPED
                    if self._scoped
                    else ConfluenceProbeVariant.UNSCOPED
                )
            )
        except ConfluenceNoVisibleSpacesError:
            # Sign-in worked; confluence_spaces_visible reports the empty site.
            return
        except HTTPError as e:
            response = e.response
            # tenant_info needs no auth: a 4xx means the URL is not a Cloud
            # site. 429 and 5xx fall through as INDETERMINATE.
            if (
                self._scoped
                and response is not None
                and _TENANT_INFO_PATH in (response.url or "")
                and 400 <= response.status_code < 500
                and response.status_code != _RATE_LIMITED_STATUS
            ):
                raise ConnectorValidationError(
                    "Onyx cannot get the Atlassian cloud id of "
                    f"{config.wiki_base} (`{_TENANT_INFO_PATH}`). Scoped API "
                    "tokens work only with Confluence Cloud; check the site URL."
                ) from e
            _raise_for_http_error(
                e,
                denied=(
                    "The credential signs in, but Confluence does not let its "
                    "user use Confluence on this site"
                ),
                not_found=(
                    f"Confluence has no API at {config.wiki_base}. Check the site "
                    "URL; a Cloud URL ends in /wiki "
                    "(https://your-domain.atlassian.net/wiki)"
                ),
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            raise UnexpectedValidationError(
                f"Onyx cannot connect to {config.wiki_base}. Check the site URL."
            ) from e


class _SpacesVisibleCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_spaces_visible",
            display_name="Spaces are visible",
            remediation=(
                "Give the token's user view permission on the spaces to index. "
                "OAuth: the `read:space:confluence` scope. Scoped API token: the "
                "`read:confluence-space.summary` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        # OAuth lists spaces through the v2 API (granular scope); scoped
        # tokens use v1 (classic scope).
        hint = _access_hint(
            context,
            config,
            oauth_scope="read:space:confluence",
            scoped_token_scope="read:confluence-space.summary",
            user_permission="view permission on the spaces to index",
        )
        try:
            first_space = next(_gateway(context).list_spaces(limit=1), None)
        except HTTPError as e:
            _raise_for_http_error(
                e, denied=f"The credential cannot list Confluence spaces. {hint}"
            )
        if first_space is None:
            raise InsufficientPermissionsError(
                f"No Confluence space is visible to this credential. {hint}"
            )


class _ConfiguredSpaceCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_configured_space",
            display_name="Configured space is readable",
            remediation=(
                "Use the space key, not the space name (e.g. `KB`; keys are case "
                "sensitive), and give the token's user view permission on it."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return _mode(form_state.config) == ConfluenceIndexingMode.SPACE

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        space_key = config.space.strip()
        try:
            _gateway(context).get_space(space_key=space_key)
        except ConfluenceSpaceNotFoundError as e:
            raise ConnectorValidationError(
                f"No space with the key `{space_key}` is visible to this "
                "credential. Check the key (keys are case sensitive), or give the "
                "token's user view permission on the space."
            ) from e
        except HTTPError as e:
            _raise_for_http_error(
                e, denied=f"The credential cannot read the space `{space_key}`"
            )
        except ConfluenceRetriesExhaustedError as e:
            raise UnexpectedValidationError(
                f"Confluence did not return the space `{space_key}`: it refused "
                "or rate limited every try. Run the checks again."
            ) from e


class _ConfiguredPageCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_configured_page",
            display_name="Configured page is readable",
            remediation=(
                "Use the number after /pages/ in the page URL, and give the "
                "token's user view permission on the page and its space."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return _mode(form_state.config) == ConfluenceIndexingMode.PAGE

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        page_id = config.page_id.strip()
        if not page_id.isdigit():
            raise ConnectorValidationError(
                f"The page ID `{page_id}` is not a number. Use the number after "
                "/pages/ in the page URL, e.g. `131368`."
            )
        try:
            page = next(
                _gateway(context).search_pages(
                    variant=ConfluenceSearchVariant.SLIM,
                    cql=f"type=page and id='{page_id}'",
                    expand=",".join(PRUNING_EXPANSION_FIELDS),
                    limit=1,
                ),
                None,
            )
        except HTTPError as e:
            _raise_for_http_error(
                e,
                denied=f"The credential cannot search for the page `{page_id}`",
                bad_request=f"Confluence rejected the page ID `{page_id}`",
            )
        if page is None:
            raise ConnectorValidationError(
                f"No page with the ID `{page_id}` is visible to this credential. "
                "Check the ID, or give the token's user view permission on the "
                "page and its space."
            )


def _validate_cql_shape(cql: str) -> None:
    """Rejects a lastModified filter and ORDER BY outside quoted values. Onyx
    adds both to the query, and the two copies conflict."""
    unquoted = _QUOTED_PATTERN.sub('""', cql)
    if _LAST_MODIFIED_PATTERN.search(unquoted):
        raise ConnectorValidationError(
            "Remove the lastModified filter from the CQL query. Onyx adds its "
            "own lastModified filter on each poll, and the two conflict."
        )
    if _ORDER_BY_PATTERN.search(unquoted):
        raise ConnectorValidationError(
            "Remove ORDER BY from the CQL query. Onyx adds filters after the "
            "query and orders the results itself."
        )


class _CqlQueryCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_cql_query",
            display_name="CQL query selects pages",
            remediation=(
                "Select only pages: join `type=page` to the other filters with "
                "AND. Use no lastModified filter and no ORDER BY. Test the query "
                "in Confluence search."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return _mode(form_state.config) == ConfluenceIndexingMode.CQL

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        _validate_cql_shape((config.cql_query or "").strip())
        try:
            # The query the indexing run sends, with its label filter.
            results = _take(
                _gateway(context).search_pages(
                    variant=ConfluenceSearchVariant.SLIM,
                    cql=_scope_cql(config),
                    expand=",".join(PRUNING_EXPANSION_FIELDS),
                    limit=_CQL_SAMPLE_RESULTS,
                ),
                _CQL_SAMPLE_RESULTS,
            )
        except HTTPError as e:
            _raise_for_http_error(
                e,
                denied="The credential cannot run CQL searches",
                bad_request="Confluence rejected the CQL query",
            )
        if not results:
            # Not FAILED: the scope can be empty on purpose (pages come later).
            raise UnexpectedValidationError(
                "The CQL query matches no page that this credential can read, so "
                "Onyx cannot verify it. Check the query if pages exist."
            )
        other_types = sorted(
            {str(result.get("type")) for result in results} - {_PAGE_TYPE}
        )
        if other_types:
            raise ConnectorValidationError(
                "The CQL query selects content that is not a page (found: "
                f"{', '.join(other_types)}). Join `type=page` to the other "
                "filters with AND. Onyx indexes pages, and reads the comments "
                "and attachments of each page itself."
            )


class _ContentReadCheck(_ConfluenceCheck):
    """Reads the first in-scope page with its body, through the same search URL
    the indexing run pages through."""

    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_content_read",
            display_name="Page content is readable",
            remediation=(
                "Give the token's user view permission on the pages to index. "
                "OAuth: the `read:confluence-content.all` and `search:confluence` "
                "scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        hint = _access_hint(
            context,
            config,
            oauth_scope="read:confluence-content.all",
            user_permission="view permission on the pages to index",
        )
        try:
            page = next(
                _gateway(context).search_pages_from_url(
                    url=build_page_retrieval_url(_scope_cql(config), 1),
                    limit=1,
                ),
                None,
            )
        except HTTPError as e:
            _raise_for_http_error(
                e,
                denied=f"The credential cannot search Confluence pages. {hint}",
                bad_request="Confluence rejected the page query",
            )
        if page is None:
            # Not FAILED: the scope can be empty on purpose (pages come later).
            raise UnexpectedValidationError(
                "The indexing scope has no page that this credential can read, so "
                f"Onyx cannot verify that page content is readable. {hint}"
            )
        body = page.get("body") or {}
        if not (body.get("storage") or body.get("view")):
            raise InsufficientPermissionsError(
                f"Confluence returned a page without its content. {hint}"
            )


class _CommentsReadCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_comments_read",
            display_name="Page comments are readable",
            required=False,
            remediation=(
                "Without comments, pages index without their comments. OAuth: "
                "the `read:confluence-content.all` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        hint = _access_hint(
            context,
            config,
            oauth_scope="read:confluence-content.all",
            user_permission="view permission on the page comments",
        )
        try:
            page = next(_sample_pages(context, config, "version"), None)
            if page is None:
                # confluence_content_read reports a scope with no pages.
                return
            next(
                gateway.search_comments(
                    cql=build_comment_cql(str(page["id"]), _label_filter(config)),
                    expand=",".join(COMMENT_EXPANSION_FIELDS),
                    limit=1,
                ),
                None,
            )
        except HTTPError as e:
            _raise_for_sample_error(
                e, denied=f"The credential cannot read page comments. {hint}"
            )


def _probe_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The smallest attachment small enough to download, or None. Attachments
    with no known size are never downloaded."""
    sized = [
        (size, attachment)
        for attachment in attachments
        if isinstance(size := attachment.get("extensions", {}).get("fileSize"), int)
    ]
    small = [item for item in sized if item[0] <= _MAX_PROBE_DOWNLOAD_BYTES]
    return min(small, key=lambda item: item[0])[1] if small else None


class _AttachmentsReadCheck(_ConfluenceCheck):
    """Lists the attachments of the first in-scope pages and downloads one. When
    the sampled pages have no attachment of a known, small size, the listing
    alone passes."""

    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_attachments_read",
            display_name="Attachments are readable",
            required=False,
            remediation=(
                "Without attachment access, attachments are not indexed. OAuth: "
                "the `readonly:content.attachment:confluence` scope. To skip "
                "attachments, turn off 'Include attachments'."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return form_state.config.include_attachments

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        hint = _access_hint(
            context,
            config,
            oauth_scope="readonly:content.attachment:confluence",
            user_permission="view permission on the page attachments",
        )
        try:
            pages = _sample_pages(context, config, "version")
            for _ in range(_SAMPLE_PAGES):
                page = next(pages, None)
                if page is None:
                    return
                page_id = str(page["id"])
                attachments = _take(
                    gateway.search_attachments(
                        variant=ConfluenceSearchVariant.CONTENT,
                        cql=build_attachment_cql(page_id, _label_filter(config)),
                        expand=",".join(ATTACHMENT_EXPANSION_FIELDS),
                        limit=_SAMPLE_ATTACHMENTS,
                    ),
                    _SAMPLE_ATTACHMENTS,
                )
                if not attachments:
                    continue
                attachment = _probe_attachment(attachments)
                if attachment is None:
                    return
                gateway.download_attachment(
                    attachment=attachment, parent_content_id=page_id
                )
                return
        except HTTPError as e:
            _raise_for_sample_error(
                e, denied=f"The credential cannot read attachments. {hint}"
            )
        except ConfluenceRetriesExhaustedError as e:
            raise UnexpectedValidationError(
                "The attachment download did not finish: Confluence refused or "
                f"rate limited every try. {hint}"
            ) from e


def _author_id(page: dict[str, Any]) -> str | None:
    """The account id (Cloud) or userkey (Data Center) of the page's last
    editor or creator."""
    for person in (
        page.get("version", {}).get("by", {}),
        page.get("history", {}).get("createdBy", {}),
    ):
        for key in ("accountId", "userKey"):
            user_id = person.get(key)
            if user_id:
                return str(user_id)
    return None


class _UserNamesCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="confluence_user_names",
            display_name="User names are readable",
            required=False,
            remediation=(
                "Without user details, mentions index as 'Unknown Confluence "
                "User'. OAuth: the `read:confluence-user` scope. API tokens: the "
                "user needs permission to view user profiles."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            page = next(_sample_pages(context, config, "version,history"), None)
        except HTTPError as e:
            _raise_for_sample_error(
                e, denied="The credential cannot search Confluence pages"
            )
        if page is None:
            return
        user_id = _author_id(page)
        if user_id is None:
            return
        try:
            name = _gateway(context).lookup_user_display_name(user_id=user_id)
        except HTTPError as e:
            _raise_for_http_error(e, denied="The credential cannot read user details")
        except ConfluenceRetriesExhaustedError as e:
            raise UnexpectedValidationError(
                "Confluence rate limited or refused every user lookup. Run the "
                "checks again."
            ) from e
        except (requests.ConnectionError, requests.Timeout) as e:
            raise UnexpectedValidationError(
                f"Onyx cannot connect to {config.wiki_base} to read user details."
            ) from e
        if name is None:
            hint = _access_hint(
                context,
                config,
                oauth_scope="read:confluence-user",
                user_permission="permission to view user profiles",
            )
            raise InsufficientPermissionsError(
                "Onyx cannot read the name of a page author, so user mentions "
                "index as 'Unknown Confluence User'. The author's account can also "
                f"be deactivated. {hint}"
            )


def build_confluence_indexing_checks() -> list[CapabilityCheck]:
    return [
        _SiteAuthCheck(scoped=False),
        _SiteAuthCheck(scoped=True),
        _SpacesVisibleCheck(),
        _ConfiguredSpaceCheck(),
        _ConfiguredPageCheck(),
        _CqlQueryCheck(),
        _ContentReadCheck(),
        _CommentsReadCheck(),
        _AttachmentsReadCheck(),
        _UserNamesCheck(),
    ]
