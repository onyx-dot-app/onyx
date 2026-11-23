"""Permissioning / AccessControl logic for JSM projects + requests.

A JSM project is backed by a Jira project, so project-level permissions are
resolved by the same Jira EE implementation. This module reuses Jira's
``get_project_permissions`` verbatim; the gateway it accepts is the Jira source
operations the JSM connector already uses.
"""

from onyx.connectors.jira.access import get_project_permissions as get_project_permissions

__all__ = ["get_project_permissions"]