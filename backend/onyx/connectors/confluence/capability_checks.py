"""Capability checks for the Confluence connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
(limit 1, or the first in-scope item) with the gateway operations that its
sync calls: the indexing checks use the indexing operations, the
permission-sync checks the permission-sync operations.

The gateway reaches the site through the bound config fields (``wiki_base``,
``is_cloud``, ``scoped_token``), so every check requires ``wiki_base`` and
``is_cloud``. On the create form the checks wait for the site URL, and
config-less credential-time runs skip them.

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
from typing import Any, NoReturn, TypeVar

import requests
from requests import HTTPError

from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE
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
    PER_PAGE_RESTRICTIONS_EXPANSION_FIELDS,
    PRUNING_EXPANSION_FIELDS,
    RESTRICTIONS_EXPANSION_FIELDS,
    ConfluenceIndexingMode,
    build_attachment_cql,
    build_base_page_cql,
    build_comment_cql,
    build_label_filter,
    build_page_cql,
    build_page_retrieval_url,
    get_indexing_mode,
)
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.connectors.confluence.source_operations import (
    OAUTH_REFRESH_TOKEN_KEY,
    Confcloud77618Error,
    ConfluenceNoVisibleSpacesError,
    ConfluenceProbeVariant,
    ConfluenceRetriesExhaustedError,
    ConfluenceSearchVariant,
    ConfluenceSourceOperations,
    ConfluenceSpaceNotFoundError,
    ConfluenceSpacePermissionsVariant,
    ConfluenceUserListVariant,
    read_dc_jsonrpc_space_subjects,
    read_dc_rest_space_subjects,
    read_dc_space_subjects,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

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


_ItemT = TypeVar("_ItemT")


def _take(items: Iterator[_ItemT], count: int) -> list[_ItemT]:
    taken: list[_ItemT] = []
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
    variant: ConfluenceSearchVariant = ConfluenceSearchVariant.CONTENT,
) -> Iterator[dict[str, Any]]:
    """In-scope pages, by default with their content as indexing reads them."""
    return _gateway(context).search_pages(
        variant=variant,
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
        capability: CredentialCapability = CredentialCapability.INDEXING,
    ) -> None:
        super().__init__(
            capability=capability,
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
            page = next(
                _sample_pages(
                    context,
                    config,
                    "version,history",
                ),
                None,
            )
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


# Permission sync. The EE registry registers these checks. Doc sync reads the
# read restrictions of each page and the permissions of every visible space.
# Group sync lists the users and the groups of each user. Both map Confluence
# users to Onyx users by email.
#
# Cloud and Data Center use different APIs, so a check that depends on the
# deployment has one instance for each, selected by ``is_cloud``.

_SAMPLE_USERS = 50
_SAMPLE_PERMISSION_USERS = 5
_APP_USER_TYPE = "app"

_SPACE_ADMIN_HINT = (
    "Only a space admin sees who can view a space. Make the token's user (for "
    "OAuth, the user who connected Confluence) a space admin of every space to "
    "sync, or a Confluence admin."
)
_DC_EMAIL_HINT = (
    "Confluence Data Center returns emails only when 'Email address visibility' "
    "(General Configuration > Security Configuration) allows it. Set it to "
    "'Public', or to 'Only visible to site administrators' with a Confluence "
    "admin as the token's user."
)
_CLOUD_EMAIL_HINT = (
    "Atlassian returns a user's email only when the user's profile shows it to "
    "anyone (Profile and visibility > Contact), or when the organization makes "
    "emails visible to apps. Users without a visible email get no access in Onyx."
)
_REMOTE_API_HINT = (
    "Turn on 'Remote API (XML-RPC & SOAP)' in General Configuration > Further "
    "Configuration, and turn off 'Secure administrator sessions' (WebSudo) in "
    "Security Configuration, or upgrade to Data Center 9.1+."
)


def _probe_space_key(
    context: CapabilityCheckContext, config: ConfluenceConnectorConfig
) -> str:
    """The configured space for a space scope, else the first visible space.
    Permission sync reads the permissions of every visible space."""
    if _mode(config) == ConfluenceIndexingMode.SPACE:
        return config.space.strip()
    try:
        space = next(_gateway(context).list_spaces(limit=1), None)
    except HTTPError as e:
        _raise_for_http_error(e, denied="The credential cannot list Confluence spaces")
    key = space.get("key") if space is not None else None
    if not key:
        raise UnexpectedValidationError(
            "No Confluence space is visible, so Onyx cannot read space "
            "permissions. confluence_spaces_visible reports why."
        )
    return str(key)


def _read_cloud_space_permissions(
    context: CapabilityCheckContext, space_key: str
) -> list[dict[str, Any]]:
    try:
        return _gateway(context).get_space_permissions(
            variant=ConfluenceSpacePermissionsVariant.CLOUD, space_key=space_key
        )
    except ConfluenceSpaceNotFoundError as e:
        raise ConnectorValidationError(
            f"The space `{space_key}` is not visible to this credential."
        ) from e
    except ConfluenceRetriesExhaustedError as e:
        raise UnexpectedValidationError(
            f"Confluence refused or rate limited every try to read the "
            f"permissions of the space `{space_key}`. {_SPACE_ADMIN_HINT}"
        ) from e
    except HTTPError as e:
        _raise_for_http_error(
            e,
            denied=(
                f"The credential cannot read the permissions of the space "
                f"`{space_key}`. {_SPACE_ADMIN_HINT}"
            ),
        )


def _cloud_subjects(permission: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    subjects = permission.get("subjects") or {}
    return subjects.get(kind, {}).get("results") or []


def _has_read_restrictions(restrictions: object) -> bool:
    if not isinstance(restrictions, dict):
        return False
    read = restrictions.get("read")
    return isinstance(read, dict) and isinstance(read.get("restrictions"), dict)


def _restrictions_hint(
    context: CapabilityCheckContext, config: ConfluenceConnectorConfig
) -> str:
    return _access_hint(
        context,
        config,
        oauth_scope="read:confluence-content.permission",
        user_permission="view permission on the pages to sync",
    )


def _probe_restrictions(
    context: CapabilityCheckContext,
    config: ConfluenceConnectorConfig,
    expand_fields: list[str],
) -> None:
    """Reads one in-scope page (and one of its attachments) with ``expand_fields``,
    and the restrictions of that page through ``restriction/byOperation``, the
    per-page lookup of the CONFCLOUD-77618 fallback."""
    gateway = _gateway(context)
    expand = ",".join(expand_fields)
    page = next(
        gateway.search_pages_with_restrictions(
            cql=_scope_cql(config), expand=expand, limit=1
        ),
        None,
    )
    if page is None:
        # confluence_content_read reports a scope with no pages.
        return
    page_id = str(page["id"])
    # Read on every run: the sync can meet CONFCLOUD-77618 on pages this
    # sample does not read, and then the fallback needs this lookup.
    page_restrictions = gateway.get_content_read_restrictions(content_id=page_id)
    if config.include_attachments:
        next(
            gateway.search_attachments_with_restrictions(
                cql=build_attachment_cql(page_id, _label_filter(config)),
                expand=expand,
                limit=1,
            ),
            None,
        )
    hint = _restrictions_hint(context, config)
    if not _has_read_restrictions(page.get("restrictions")):
        raise InsufficientPermissionsError(
            f"Confluence returned a page without its read restrictions. {hint}"
        )
    if page_restrictions is None:
        raise InsufficientPermissionsError(
            "Confluence does not return the restrictions of a readable page "
            "(restriction/byOperation). Permission sync needs this lookup when "
            f"CONFCLOUD-77618 blocks the batch read. {hint}"
        )


class _PageRestrictionsReadCheck(_ConfluenceCheck):
    """Reads page restrictions as permission sync does. On CONFCLOUD-77618 the
    sync restarts with per-page lookups, so the check then proves those."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_page_restrictions_read",
            display_name="Page restrictions are readable",
            remediation=(
                "Give the token's user view permission on the pages to sync. "
                "OAuth: the `read:confluence-content.permission` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            try:
                _probe_restrictions(context, config, RESTRICTIONS_EXPANSION_FIELDS)
            except Confcloud77618Error:
                # confluence_restrictions_batch_read reports the slower sync.
                _probe_restrictions(
                    context, config, PER_PAGE_RESTRICTIONS_EXPANSION_FIELDS
                )
        except HTTPError as e:
            _raise_for_sample_error(
                e,
                denied=(
                    "The credential cannot read page restrictions. "
                    f"{_restrictions_hint(context, config)}"
                ),
            )


class _RestrictionsBatchReadCheck(_ConfluenceCheck):
    """Reads the restrictions of a few pages and their ancestors in one
    request. CONFCLOUD-77618 makes that request fail when an ancestor is a
    draft, outdated or trashed page; permission sync then reads each page's
    ancestors one at a time."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_restrictions_batch_read",
            display_name="Ancestor restrictions read in one request",
            required=False,
            remediation=(
                "No action is necessary: permission sync is slower but correct. "
                "To make it fast again, delete or publish the draft, outdated or "
                "trashed parent pages (CONFCLOUD-77618)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            _take(
                _gateway(context).search_pages_with_restrictions(
                    cql=_scope_cql(config),
                    expand=",".join(RESTRICTIONS_EXPANSION_FIELDS),
                    limit=_SAMPLE_PAGES,
                ),
                _SAMPLE_PAGES,
            )
        except Confcloud77618Error as e:
            raise ConnectorValidationError(
                "Confluence cannot read the restrictions of a parent page "
                "(CONFCLOUD-77618), so permission sync reads the parent pages "
                "of each page one at a time. Sync is slower but correct."
            ) from e
        except HTTPError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read page restrictions, so this check cannot run. "
                "confluence_page_restrictions_read reports why."
            ) from e


class _CloudSpacePermissionsCheck(_ConfluenceCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_space_permissions_read",
            display_name="Space permissions are readable",
            remediation=(
                "Make the token's user a space admin of every space to sync, or "
                "a Confluence admin. OAuth: the `read:confluence-space.summary` "
                "scope."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return form_state.config.is_cloud

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        space_key = _probe_space_key(context, config)
        permissions = _read_cloud_space_permissions(context, space_key)
        if not any(
            _cloud_subjects(permission, kind)
            for permission in permissions
            for kind in ("user", "group")
        ):
            raise InsufficientPermissionsError(
                f"Confluence returned the permissions of the space `{space_key}` "
                f"without the users and groups they grant. {_SPACE_ADMIN_HINT}"
            )


def _raise_for_dc_permission_error(error: HTTPError, *, space_key: str) -> NoReturn:
    _raise_for_http_error(
        error,
        denied=(
            f"The credential cannot read the permissions of the space "
            f"`{space_key}`. {_SPACE_ADMIN_HINT}"
        ),
    )


class _DcRestSpacePermissionsCheck(_ConfluenceCheck):
    """The REST space-permissions API of Data Center 9.1+. A Data Center without
    it (before 9.1) passes: permission sync then uses JSON-RPC."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_space_permissions_read_dc_rest",
            display_name="Space permissions are readable (Data Center 9.1+ REST)",
            remediation=(
                "Make the token's user a space admin of every space to sync, or "
                "a Confluence admin. Without admin rights this API returns HTTP "
                "500 (CONFSERVER-99908)."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return not form_state.config.is_cloud

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        space_key = _probe_space_key(context, config)
        try:
            subjects = read_dc_rest_space_subjects(_gateway(context), space_key)
        except InsufficientPermissionsError as e:
            raise InsufficientPermissionsError(
                f"Confluence returned HTTP 500 for the permissions of the space "
                f"`{space_key}`, which means the user is not an admin "
                f"(CONFSERVER-99908). {_SPACE_ADMIN_HINT}"
            ) from e
        except HTTPError as e:
            _raise_for_dc_permission_error(e, space_key=space_key)
        if subjects is None:
            logger.debug(
                "No DC REST space-permissions API; the JSON-RPC check applies."
            )
            return
        if not subjects.users and not subjects.groups:
            raise InsufficientPermissionsError(
                f"Confluence returned no view permissions for the space "
                f"`{space_key}`. {_SPACE_ADMIN_HINT}"
            )


class _DcJsonRpcSpacePermissionsCheck(_ConfluenceCheck):
    """The JSON-RPC space permissions of Data Center before 9.1, also used when
    the REST API is missing. Passes when permission sync uses REST."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_space_permissions_read_dc_jsonrpc",
            display_name="Space permissions are readable (Data Center JSON-RPC)",
            remediation=(
                f"{_REMOTE_API_HINT} Make the token's user a space admin of every "
                "space to sync, or a Confluence admin."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return not form_state.config.is_cloud

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        space_key = _probe_space_key(context, config)
        try:
            rest_subjects = read_dc_rest_space_subjects(gateway, space_key)
        except (HTTPError, InsufficientPermissionsError):
            logger.debug(
                "Permission sync uses the DC REST API; "
                "confluence_space_permissions_read_dc_rest reports its errors."
            )
            return
        if rest_subjects is not None:
            logger.debug("Permission sync uses the DC REST API.")
            return
        try:
            subjects = read_dc_jsonrpc_space_subjects(gateway, space_key)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                raise ConnectorValidationError(
                    "Confluence rejected the JSON-RPC call for space permissions "
                    f"(HTTP 401). {_REMOTE_API_HINT}"
                ) from e
            _raise_for_dc_permission_error(e, space_key=space_key)
        if not subjects.raw_permissions:
            raise InsufficientPermissionsError(
                f"Confluence returned no permissions for the space `{space_key}` "
                f"over JSON-RPC. {_SPACE_ADMIN_HINT}"
            )


class _PermissionUserEmailsCheck(_ConfluenceCheck):
    """Users in the space permissions have emails. Cloud returns them inline;
    Data Center needs a lookup for each user."""

    def __init__(self, *, is_cloud: bool) -> None:
        self._is_cloud = is_cloud
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=(
                "confluence_permission_user_emails"
                if is_cloud
                else "confluence_permission_user_emails_dc"
            ),
            display_name="Users in permissions have emails",
            remediation=_CLOUD_EMAIL_HINT if is_cloud else _DC_EMAIL_HINT,
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return form_state.config.is_cloud == self._is_cloud

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        space_key = _probe_space_key(context, config)
        if self._is_cloud:
            self._run_cloud(context, space_key)
        else:
            self._run_dc(context, space_key)

    def _run_cloud(self, context: CapabilityCheckContext, space_key: str) -> None:
        try:
            permissions = _read_cloud_space_permissions(context, space_key)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the space permissions, so this check cannot "
                "run. confluence_space_permissions_read reports why."
            ) from e
        # Permission sync reads only the first user of each permission.
        users = [
            subjects[0]
            for permission in permissions
            if (subjects := _cloud_subjects(permission, "user"))
            and subjects[0].get("accountType") != _APP_USER_TYPE
        ]
        if users and not any(user.get("email") for user in users):
            raise InsufficientPermissionsError(
                f"No user in the permissions of the space `{space_key}` has a "
                f"visible email, so their access cannot map to Onyx users. "
                f"{_CLOUD_EMAIL_HINT}"
            )

    def _run_dc(self, context: CapabilityCheckContext, space_key: str) -> None:
        gateway = _gateway(context)
        try:
            subjects = read_dc_space_subjects(gateway, space_key)
        except (HTTPError, ConnectorValidationError) as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the space permissions, so this check cannot "
                "run. The space-permission checks report why."
            ) from e
        sample = sorted(subjects.users)[:_SAMPLE_PERMISSION_USERS]
        if sample and not any(
            gateway.get_user_email(
                variant=subjects.user_email_variant(), user=user, cached=False
            )
            for user in sample
        ):
            raise InsufficientPermissionsError(
                f"Onyx cannot read the email of any user in the permissions of "
                f"the space `{space_key}`, so their access cannot map to Onyx "
                f"users. {_DC_EMAIL_HINT}"
            )


class _AnonymousSpaceAccessCheck(_ConfluenceCheck):
    """Data Center 9.1+ reads anonymous access with its own call. Before 9.1 the
    call returns 404, which reads as no anonymous access."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="confluence_anonymous_space_access",
            display_name="Anonymous space access is readable",
            required=False,
            remediation=(
                "Without it, spaces open to anonymous users sync as not public. "
                "Make the token's user a Confluence admin (CONFSERVER-99908)."
            ),
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return not form_state.config.is_cloud

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        space_key = _probe_space_key(context, config)
        try:
            _gateway(context).get_anonymous_space_permissions(space_key=space_key)
        except InsufficientPermissionsError as e:
            raise InsufficientPermissionsError(
                f"Confluence returned HTTP 500 for the anonymous permissions of "
                f"the space `{space_key}`, which means the user is not an admin "
                f"(CONFSERVER-99908). {_SPACE_ADMIN_HINT}"
            ) from e
        except HTTPError as e:
            _raise_for_dc_permission_error(e, space_key=space_key)


def _user_list_variant(is_cloud: bool) -> ConfluenceUserListVariant:
    return ConfluenceUserListVariant.CLOUD if is_cloud else ConfluenceUserListVariant.DC


def _user_listing_hint(
    context: CapabilityCheckContext, config: ConfluenceConnectorConfig
) -> str:
    return _access_hint(
        context,
        config,
        oauth_scope="read:confluence-user",
        user_permission="the global permission to browse users",
    )


def _sample_users(
    context: CapabilityCheckContext,
    config: ConfluenceConnectorConfig,
    is_cloud: bool,
) -> list[ConfluenceUser]:
    """The first listed users, people before apps. Reads
    CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE instead when it is set."""
    try:
        users = _take(
            _gateway(context).list_users(
                variant=_user_list_variant(is_cloud), limit=_SAMPLE_USERS
            ),
            _SAMPLE_USERS,
        )
    except HTTPError as e:
        _raise_for_http_error(
            e,
            denied=(
                "The credential cannot list Confluence users. "
                f"{_user_listing_hint(context, config)}"
            ),
        )
    return sorted(users, key=lambda user: user.type == _APP_USER_TYPE)


class _GroupSyncCheck(_ConfluenceCheck):
    """A group-sync check with one instance each for Cloud and Data Center."""

    def __init__(
        self,
        *,
        is_cloud: bool,
        check_id: str,
        display_name: str,
        remediation: str,
    ) -> None:
        self._is_cloud = is_cloud
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=check_id if is_cloud else f"{check_id}_dc",
            display_name=display_name,
            remediation=remediation,
        )

    def applies(self, form_state: FormState[ConfluenceConnectorConfig]) -> bool:
        return form_state.config.is_cloud == self._is_cloud


class _UserListingCheck(_GroupSyncCheck):
    def __init__(self, *, is_cloud: bool) -> None:
        super().__init__(
            is_cloud=is_cloud,
            check_id="confluence_user_listing",
            display_name="Users can be listed",
            remediation=(
                "Give the token's user the global permission to browse users. "
                "OAuth: the `read:confluence-user` scope. Data Center before "
                "10.1 can list too few users (CONFSERVER-95999); set "
                "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE to list them."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        if not _sample_users(context, config, self._is_cloud):
            raise InsufficientPermissionsError(
                f"Confluence listed no users. {_user_listing_hint(context, config)}"
            )


class _GroupMembershipCheck(_GroupSyncCheck):
    def __init__(self, *, is_cloud: bool) -> None:
        super().__init__(
            is_cloud=is_cloud,
            check_id="confluence_group_membership",
            display_name="Group memberships are readable",
            remediation=(
                "Give the token's user the global permission to browse users. "
                "OAuth: the `read:confluence-groups` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        hint = _access_hint(
            context,
            config,
            oauth_scope="read:confluence-groups",
            user_permission="the global permission to browse users",
        )
        users = _sample_users(context, config, self._is_cloud)
        if not users:
            raise UnexpectedValidationError(
                "Confluence listed no users, so Onyx cannot read group "
                "memberships. confluence_user_listing reports why."
            )
        try:
            for user in users[:_SAMPLE_PERMISSION_USERS]:
                if next(gateway.list_user_groups(user_id=user.user_id), None):
                    return
        except HTTPError as e:
            _raise_for_http_error(
                e, denied=f"The credential cannot read group memberships. {hint}"
            )
        # The reads succeeded: the sampled users can have no groups, and group
        # sync reads every user.
        raise UnexpectedValidationError(
            "The first listed users are in no group, so Onyx cannot verify that "
            f"group memberships are readable. {hint}"
        )


class _GroupUserEmailsCheck(_GroupSyncCheck):
    """Listed users have emails. The Data Center user list carries none, so
    each one needs a lookup; the profile override carries its own emails."""

    def __init__(self, *, is_cloud: bool) -> None:
        super().__init__(
            is_cloud=is_cloud,
            check_id="confluence_group_user_emails",
            display_name="Listed users have emails",
            remediation=_CLOUD_EMAIL_HINT if is_cloud else _DC_EMAIL_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        people = [
            user
            for user in _sample_users(context, config, self._is_cloud)
            if user.type != _APP_USER_TYPE
        ]
        if not people:
            # confluence_user_listing reports an empty listing.
            return
        if self._is_cloud or CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE:
            # The listing carries the emails, so every listed person costs
            # nothing extra.
            has_email = any(user.email for user in people)
        else:
            has_email = any(
                gateway.get_listed_user_email(username=user.username, cached=False)
                for user in people[:_SAMPLE_PERMISSION_USERS]
                if user.username
            )
        if not has_email:
            raise InsufficientPermissionsError(
                "No listed user has an email, so group members cannot map to "
                f"Onyx users. {_CLOUD_EMAIL_HINT if self._is_cloud else _DC_EMAIL_HINT}"
            )


def build_confluence_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _PageRestrictionsReadCheck(),
        _RestrictionsBatchReadCheck(),
        _CloudSpacePermissionsCheck(),
        _DcRestSpacePermissionsCheck(),
        _DcJsonRpcSpacePermissionsCheck(),
        _PermissionUserEmailsCheck(is_cloud=True),
        _PermissionUserEmailsCheck(is_cloud=False),
        _AnonymousSpaceAccessCheck(),
    ]


def build_confluence_group_sync_checks() -> list[CapabilityCheck]:
    return [
        check
        for is_cloud in (True, False)
        for check in (
            _UserListingCheck(is_cloud=is_cloud),
            _GroupMembershipCheck(is_cloud=is_cloud),
            _GroupUserEmailsCheck(is_cloud=is_cloud),
        )
    ]
