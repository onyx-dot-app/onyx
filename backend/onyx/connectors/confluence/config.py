from enum import Enum
from typing import Annotated, Any, Self
from urllib.parse import urlparse

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
    CONFLUENCE_TIMEZONE_OFFSET,
    CONTINUE_ON_CONNECTOR_FAILURE,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)

# Set by the Confluence Cloud OAuth finalize step to the site the user authorized.
_OAUTH_WIKI_BASE_KEY = "wiki_base"

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_SPACE = "space"
_PAGE_ID = "page_id"
_INDEX_RECURSIVELY = "index_recursively"
_CQL_QUERY = "cql_query"
_LABELS_TO_SKIP = "labels_to_skip"
_INDEXING_SCOPE_FIELDS = (_SPACE, _PAGE_ID, _INDEX_RECURSIVELY, _CQL_QUERY)


class ConfluenceIndexingMode(str, Enum):
    CQL = "cql"
    PAGE = "page"
    SPACE = "space"
    EVERYTHING = "everything"


def get_indexing_mode(
    *, space: str, page_id: str, cql_query: str | None
) -> ConfluenceIndexingMode:
    """The scope the connector indexes. The config can hold values for several
    modes (the form sends every tab's fields); the first set one wins, in this
    order: CQL query, page id, space, everything. Blank values are not set."""
    if cql_query and cql_query.strip():
        return ConfluenceIndexingMode.CQL
    if page_id.strip():
        return ConfluenceIndexingMode.PAGE
    if space.strip():
        return ConfluenceIndexingMode.SPACE
    return ConfluenceIndexingMode.EVERYTHING


def _site(url: str) -> tuple[str, str]:
    """The URL's scheme and host. The scheme counts: an http URL for an
    https-authorized site would send the token unencrypted."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.scheme.lower(), parsed.netloc.lower()


class ConfluenceCredentialBinding(CredentialBinding):
    # Document ids are page and attachment URLs on this site.
    wiki_base: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # Adds "/wiki" to the document id URLs.
    is_cloud: Annotated[bool, FieldPolicy(FieldClass.IDENTITY)]
    # Only selects the API gateway: document ids keep wiki_base.
    scoped_token: Annotated[bool, _COSMETIC] = False

    def validate_credential(self, credential_json: dict[str, Any]) -> None:
        authorized_wiki_base = credential_json.get(_OAUTH_WIKI_BASE_KEY)
        if not authorized_wiki_base:
            return
        if _site(self.wiki_base) != _site(authorized_wiki_base):
            raise ConnectorValidationError(
                f"The site URL {self.wiki_base} is not the Confluence site this "
                f"account was authorized for ({authorized_wiki_base})."
            )


class ConfluenceConnectorConfig(ConfluenceCredentialBinding, ConnectorConfig):
    # The indexing scope fields get their directions from classify_scope_change.
    # The descriptors apply only when a stored config does not validate.
    space: Annotated[
        str,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_PAGE_ID, _CQL_QUERY),
        ),
    ] = ""
    page_id: Annotated[
        str,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_SPACE, _INDEX_RECURSIVELY, _CQL_QUERY),
        ),
    ] = ""
    index_recursively: Annotated[
        bool,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeToggle(widens_when=True),
            depends_on=(_SPACE, _PAGE_ID, _CQL_QUERY),
        ),
    ] = False
    cql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    continue_on_failure: Annotated[bool, _COSMETIC] = CONTINUE_ON_CONNECTOR_FAILURE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
    # Sets the poll window bounds in CQL. A wrong offset can miss updates,
    # so a change re-indexes everything.
    timezone_offset: Annotated[float, FieldPolicy(FieldClass.BEHAVIOR)] = (
        CONFLUENCE_TIMEZONE_OFFSET
    )
    # Attachments are documents of their own.
    include_attachments: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = True

    def indexing_mode(self) -> ConfluenceIndexingMode:
        return get_indexing_mode(
            space=self.space, page_id=self.page_id, cql_query=self.cql_query
        )

    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        directions = {
            name: _indexing_scope_direction(old, new) for name in _INDEXING_SCOPE_FIELDS
        }
        # The label filter also drops labeled comments from the page text,
        # which only a from-beginning run rewrites.
        if set(new.labels_to_skip) - set(old.labels_to_skip):
            directions[_LABELS_TO_SKIP] = ScopeDirection.BOTH
        return directions


def _indexing_scope_direction(
    old: ConfluenceConnectorConfig, new: ConfluenceConnectorConfig
) -> ScopeDirection:
    """One direction for the space, page and CQL fields together. A field
    of a mode that is not in use has no effect."""
    old_mode = old.indexing_mode()
    new_mode = new.indexing_mode()
    if old_mode != new_mode:
        if old_mode == ConfluenceIndexingMode.EVERYTHING:
            return ScopeDirection.NARROW
        if new_mode == ConfluenceIndexingMode.EVERYTHING:
            return ScopeDirection.WIDEN
        return ScopeDirection.UNKNOWN

    match new_mode:
        case ConfluenceIndexingMode.EVERYTHING:
            return ScopeDirection.NONE
        case ConfluenceIndexingMode.SPACE:
            if old.space.strip() == new.space.strip():
                return ScopeDirection.NONE
            return ScopeDirection.BOTH
        case ConfluenceIndexingMode.PAGE:
            if old.page_id.strip() != new.page_id.strip():
                return ScopeDirection.BOTH
            if old.index_recursively == new.index_recursively:
                return ScopeDirection.NONE
            return (
                ScopeDirection.WIDEN if new.index_recursively else ScopeDirection.NARROW
            )
        case ConfluenceIndexingMode.CQL:
            if (old.cql_query or "").strip() == (new.cql_query or "").strip():
                return ScopeDirection.NONE
            return ScopeDirection.UNKNOWN
