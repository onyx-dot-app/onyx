"""Capability checks for the Jira Service Management (JSM) connector.

A JSM project is backed by a Jira project and served by the same Atlassian REST
API, so the probes are identical to Jira's: the same sign-in, project-list,
JQL and issue-read checks for indexing, the same permission-scheme / project-role
/ user-email checks for document permission sync, and the same group listing /
membership / member-email checks for group sync.

The only difference is the connector config model: a JSM connector stores a
:class:`JsmConnectorConfig`, so every check must read its config through that
class (the checks runner builds the form state with the source's own config
class and rejects a check that reads a different one). Each JSM check therefore
subclasses its Jira counterpart and overrides ``config_class``; the probe logic
is inherited unchanged.
"""

from onyx.connectors.capability_checks.models import CapabilityCheck
from onyx.connectors.jira.capability_checks import (
    _ConfiguredProjectCheck as _JiraConfiguredProjectCheck,
)
from onyx.connectors.jira.capability_checks import (
    _GroupListingCheck as _JiraGroupListingCheck,
)
from onyx.connectors.jira.capability_checks import (
    _GroupListingCompleteCheck as _JiraGroupListingCompleteCheck,
)
from onyx.connectors.jira.capability_checks import (
    _GroupMemberEmailsCheck as _JiraGroupMemberEmailsCheck,
)
from onyx.connectors.jira.capability_checks import (
    _GroupMembershipCheck as _JiraGroupMembershipCheck,
)
from onyx.connectors.jira.capability_checks import (
    _IssueReadCheck as _JiraIssueReadCheck,
)
from onyx.connectors.jira.capability_checks import (
    _JqlQueryCheck as _JiraJqlQueryCheck,
)
from onyx.connectors.jira.capability_checks import (
    _PermissionSchemeReadCheck as _JiraPermissionSchemeReadCheck,
)
from onyx.connectors.jira.capability_checks import (
    _PermissionUserEmailsCheck as _JiraPermissionUserEmailsCheck,
)
from onyx.connectors.jira.capability_checks import (
    _ProjectAccessMappableCheck as _JiraProjectAccessMappableCheck,
)
from onyx.connectors.jira.capability_checks import (
    _ProjectRolesReadCheck as _JiraProjectRolesReadCheck,
)
from onyx.connectors.jira.capability_checks import (
    _ProjectsVisibleCheck as _JiraProjectsVisibleCheck,
)
from onyx.connectors.jira.capability_checks import (
    _SiteAuthCheck as _JiraSiteAuthCheck,
)
from onyx.connectors.jsm.config import JsmConnectorConfig

__all__ = [
    "build_jsm_indexing_checks",
    "build_jsm_doc_permission_sync_checks",
    "build_jsm_group_sync_checks",
]


# --- Indexing checks -------------------------------------------------------


class _SiteAuthCheck(_JiraSiteAuthCheck):
    config_class = JsmConnectorConfig


class _ProjectsVisibleCheck(_JiraProjectsVisibleCheck):
    config_class = JsmConnectorConfig


class _ConfiguredProjectCheck(_JiraConfiguredProjectCheck):
    config_class = JsmConnectorConfig


class _JqlQueryCheck(_JiraJqlQueryCheck):
    config_class = JsmConnectorConfig


class _IssueReadCheck(_JiraIssueReadCheck):
    config_class = JsmConnectorConfig


# --- Document permission sync checks ---------------------------------------


class _PermissionSchemeReadCheck(_JiraPermissionSchemeReadCheck):
    config_class = JsmConnectorConfig


class _ProjectAccessMappableCheck(_JiraProjectAccessMappableCheck):
    config_class = JsmConnectorConfig


class _ProjectRolesReadCheck(_JiraProjectRolesReadCheck):
    config_class = JsmConnectorConfig


class _PermissionUserEmailsCheck(_JiraPermissionUserEmailsCheck):
    config_class = JsmConnectorConfig


# --- Group sync checks -----------------------------------------------------


class _GroupListingCheck(_JiraGroupListingCheck):
    config_class = JsmConnectorConfig


class _GroupListingCompleteCheck(_JiraGroupListingCompleteCheck):
    config_class = JsmConnectorConfig


class _GroupMembershipCheck(_JiraGroupMembershipCheck):
    config_class = JsmConnectorConfig


class _GroupMemberEmailsCheck(_JiraGroupMemberEmailsCheck):
    config_class = JsmConnectorConfig


def build_jsm_indexing_checks() -> list[CapabilityCheck]:
    return [
        _SiteAuthCheck(scoped=False),
        _SiteAuthCheck(scoped=True),
        _ProjectsVisibleCheck(),
        _ConfiguredProjectCheck(),
        _JqlQueryCheck(),
        _IssueReadCheck(),
    ]


def build_jsm_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _PermissionSchemeReadCheck(),
        _ProjectAccessMappableCheck(),
        _ProjectRolesReadCheck(),
        _PermissionUserEmailsCheck(),
    ]


def build_jsm_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _GroupListingCheck(),
        _GroupListingCompleteCheck(),
        _GroupMembershipCheck(),
        _GroupMemberEmailsCheck(),
    ]