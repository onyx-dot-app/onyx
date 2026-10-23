import re
from enum import Enum
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import field_validator

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
    CONFLUENCE_TIMEZONE_OFFSET,
    CONTINUE_ON_CONNECTOR_FAILURE,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.atlassian_query import has_last_modified_filter, has_order_by
from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
    HierarchyBreakdownSection,
    field_format_error,
)
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
from onyx.connectors.planning_rule import ConnectorChangeOverride
from onyx.db.enums import HierarchyNodeType

# Set by the Confluence Cloud OAuth finalize step to the site the user authorized.
_OAUTH_WIKI_BASE_KEY = "wiki_base"

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_SPACE = "space"
_PAGE_ID = "page_id"
_INDEX_RECURSIVELY = "index_recursively"
_CQL_QUERY = "cql_query"
_LABELS_TO_SKIP = "labels_to_skip"
_INDEXING_SCOPE_FIELDS = (_SPACE, _PAGE_ID, _INDEX_RECURSIVELY, _CQL_QUERY)

PAGE_ID_FORMAT_ERROR = "Enter the number from the page URL, e.g. 131368."
SPACE_KEY_FORMAT_ERROR = "Enter a space key, e.g. ENG."
CQL_LAST_MODIFIED_ERROR = "Unsupported filter: lastModified. Each sync adds its own."
CQL_ORDER_BY_ERROR = (
    "Unsupported clause: ORDER BY. Each sync orders the results itself."
)

# Confluence document_id is the page URL. Reindex inputs come from
# IndexAttemptError rows (also URLs). Two URL shapes show up in the wild:
#   - /spaces/KEY/pages/<id>/Title-slug  (Cloud + modern Server/DC)
#   - /pages/viewpage.action?pageId=<id> (legacy Server)
_PAGE_ID_FROM_URL_PATTERNS = [
    re.compile(r"/pages/(\d+)(?:/|$)"),
    re.compile(r"[?&]pageId=(\d+)"),
]


def extract_page_id_from_url(doc_id: str) -> str | None:
    for pat in _PAGE_ID_FROM_URL_PATTERNS:
        match = pat.search(doc_id)
        if match:
            return match.group(1)
    return None


def parse_scope_keys(value: str) -> tuple[str, ...]:
    """The keys of a comma-separated space or page setting, in order, without
    blanks or repeats. A setting saved before lists were allowed holds one."""
    keys: list[str] = []
    for key in (part.strip() for part in value.split(",")):
        if key and key not in keys:
            keys.append(key)
    return tuple(keys)


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
    order: CQL query, page ids, spaces, everything. Blank values are not set.
    In PAGE mode the spaces count too: the scope is their union."""
    if cql_query and cql_query.strip():
        return ConfluenceIndexingMode.CQL
    if parse_scope_keys(page_id):
        return ConfluenceIndexingMode.PAGE
    if parse_scope_keys(space):
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
    # The indexing scope fields get their directions from confluence_planning_rule.
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

    @field_validator(_PAGE_ID)
    @classmethod
    def _page_id_is_a_number(cls, value: str) -> str:
        page_ids = parse_scope_keys(value)
        # Separators alone, such as ",", name no page.
        if value.strip() and not page_ids:
            raise field_format_error(PAGE_ID_FORMAT_ERROR)
        # isdigit alone accepts digits such as "²".
        for page_id in page_ids:
            if not (page_id.isascii() and page_id.isdigit()):
                raise field_format_error(PAGE_ID_FORMAT_ERROR)
        return value

    @field_validator(_SPACE)
    @classmethod
    def _space_names_a_key(cls, value: str) -> str:
        # Separators alone, such as ",", name no space.
        if value.strip() and not parse_scope_keys(value):
            raise field_format_error(SPACE_KEY_FORMAT_ERROR)
        return value

    # Each sync adds a lastModified filter and ORDER BY to the query, and a
    # second copy conflicts with them.
    @field_validator(_CQL_QUERY)
    @classmethod
    def _cql_has_no_sync_clauses(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if has_last_modified_filter(value):
            raise field_format_error(CQL_LAST_MODIFIED_ERROR)
        if has_order_by(value):
            raise field_format_error(CQL_ORDER_BY_ERROR)
        return value

    def indexing_mode(self) -> ConfluenceIndexingMode:
        return get_indexing_mode(
            space=self.space, page_id=self.page_id, cql_query=self.cql_query
        )

    def hierarchy_breakdown_sections(self) -> list[HierarchyBreakdownSection]:
        """Every space, plus the configured pages. Only the fields of the
        indexing mode in use name nodes: the form also sends the other tabs'
        fields."""
        mode = self.indexing_mode()
        configured_space = (
            parse_scope_keys(self.space)
            if mode in (ConfluenceIndexingMode.SPACE, ConfluenceIndexingMode.PAGE)
            else ()
        )
        configured_page = (
            parse_scope_keys(self.page_id)
            if mode == ConfluenceIndexingMode.PAGE
            else ()
        )
        return [
            # Two spaces cannot have keys that differ only in case
            # (CONFSERVER-40303), so a match without case cannot pick the
            # wrong space. A space that the indexing did not find has no
            # node, so it shows as not indexed with either rule.
            HierarchyBreakdownSection(
                node_type=HierarchyNodeType.SPACE,
                expected_node_keys=configured_space,
                case_insensitive_keys=True,
                config_field="space",
            ),
            HierarchyBreakdownSection(
                node_type=HierarchyNodeType.PAGE,
                expected_node_keys=configured_page,
                include_unexpected_nodes=False,
                config_field="page_id",
                # A page gets a hierarchy node only when it has child pages or
                # attachments. A leaf page is only a document.
                nodes_can_be_documents=True,
            ),
        ]

    @classmethod
    def hierarchy_node_key(cls, node_type: HierarchyNodeType, raw_node_id: str) -> str:
        """A page node's raw id is the page URL (the document id). The config
        names a page by its numeric id. A space node's raw id is the space key."""
        if node_type == HierarchyNodeType.PAGE:
            return extract_page_id_from_url(raw_node_id) or raw_node_id
        return raw_node_id


def _keys_direction(old: str, new: str) -> ScopeDirection:
    """How a list of space keys or page ids changed: only added keys widen
    the scope, only removed keys narrow it."""
    old_keys = set(parse_scope_keys(old))
    new_keys = set(parse_scope_keys(new))
    if old_keys == new_keys:
        return ScopeDirection.NONE
    if old_keys < new_keys:
        return ScopeDirection.WIDEN
    if new_keys < old_keys:
        return ScopeDirection.NARROW
    return ScopeDirection.BOTH


def _combine_directions(a: ScopeDirection, b: ScopeDirection) -> ScopeDirection:
    if a == ScopeDirection.NONE:
        return b
    if b == ScopeDirection.NONE or a == b:
        return a
    return ScopeDirection.BOTH


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
            return _keys_direction(old.space, new.space)
        case ConfluenceIndexingMode.PAGE:
            keys = _combine_directions(
                _keys_direction(old.space, new.space),
                _keys_direction(old.page_id, new.page_id),
            )
            if old.index_recursively == new.index_recursively:
                return keys
            return _combine_directions(
                keys,
                ScopeDirection.WIDEN
                if new.index_recursively
                else ScopeDirection.NARROW,
            )
        case ConfluenceIndexingMode.CQL:
            if (old.cql_query or "").strip() == (new.cql_query or "").strip():
                return ScopeDirection.NONE
            return ScopeDirection.UNKNOWN


def confluence_planning_rule(
    old: ConfluenceConnectorConfig, new: ConfluenceConnectorConfig
) -> ConnectorChangeOverride:
    directions = {
        name: _indexing_scope_direction(old, new) for name in _INDEXING_SCOPE_FIELDS
    }
    # The label filter also drops labeled comments from the page text,
    # which only a from-beginning run rewrites.
    if set(new.labels_to_skip) - set(old.labels_to_skip):
        directions[_LABELS_TO_SKIP] = ScopeDirection.BOTH
    return ConnectorChangeOverride(scope_directions=directions)
