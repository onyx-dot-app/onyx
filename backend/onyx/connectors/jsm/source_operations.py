"""JSM source operations gateway.

A JSM project is served by the same Atlassian REST API as Jira, so the JSM
gateway exposes exactly the same operations as :class:`JiraSourceOperations`
(``myself``, project listing/read, enhanced-JQL and v2 JQL issue search, bulk
fetch, permission-scheme / project-role / user reads, and group listing /
membership). Rather than duplicate that ~300-line implementation, this gateway
binds the Jira operations onto a ``DocumentSource.JSM`` gateway.

Each operation is assigned from :class:`JiraSourceOperations` under its own
name. The ``@source_operation`` stamp lives on the underlying function object
and carries ``spec.name`` equal to that name, so ``SourceOperations``'
``__init_subclass__`` scan validates and registers every operation exactly as if
it were defined here -- the import-time anti-drift guarantees (one gateway per
source, every public method classified, ``sdk_modules`` declared) all still
hold. The private client plumbing is reused verbatim as well.

The result: JSM documents are crawled and permission-synced by the same code
path as Jira, but attributed to ``DocumentSource.JSM`` and keyed to the JSM
connector's config.
"""

from typing import Any

from jira import JIRA

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.config import JiraCredentialBinding
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.source_operations import SourceOperations

__all__ = ["JsmSourceOperations"]


class JsmSourceOperations(SourceOperations):
    """The JSM gateway: Jira's source operations bound to ``DocumentSource.JSM``.

    JSM service-desk requests are Jira issues, so every operation is identical
    to Jira's. The methods below are the Jira implementations, re-bound under
    this gateway so the capability-check runner constructs a JSM gateway for
    ``DocumentSource.JSM`` and the checks exercise the same REST calls.
    """

    source = DocumentSource.JSM
    # The gateway wraps the ``jira`` SDK, exactly like the Jira gateway.
    sdk_modules = ("jira",)
    # The gateway reads only the credential-bound fields (site URL, scoped
    # token) -- the same binding the Jira gateway uses.
    config_keys = frozenset(JiraCredentialBinding.model_fields)

    # Per-instance client cache (set lazily by ``_client``); class-level default
    # so the first access resolves to ``None`` rather than raising.
    _cached_client: JIRA | None = None
    _cached_fast_client: JIRA | None = None

    # --- Private client plumbing (reused verbatim from the Jira gateway) -----
    _client_build_lock = JiraSourceOperations._client_build_lock
    _binding = JiraSourceOperations._binding
    _credentials = JiraSourceOperations._credentials
    _is_cloud = JiraSourceOperations._is_cloud
    _api_url = JiraSourceOperations._api_url
    _build_client = JiraSourceOperations._build_client
    _client = JiraSourceOperations._client

    # --- Indexing operations ------------------------------------------------
    get_myself = JiraSourceOperations.get_myself
    list_projects = JiraSourceOperations.list_projects
    get_project = JiraSourceOperations.get_project
    search_issue_ids = JiraSourceOperations.search_issue_ids
    bulk_fetch_issues = JiraSourceOperations.bulk_fetch_issues
    search_issues = JiraSourceOperations.search_issues

    # --- Document permission sync operations --------------------------------
    get_project_permission_scheme = (
        JiraSourceOperations.get_project_permission_scheme
    )
    get_project_role = JiraSourceOperations.get_project_role
    get_user = JiraSourceOperations.get_user

    # --- External group sync operations -------------------------------------
    list_groups = JiraSourceOperations.list_groups
    get_group_members_page = JiraSourceOperations.get_group_members_page