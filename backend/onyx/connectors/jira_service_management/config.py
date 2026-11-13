"""Typed configuration for the Jira Service Management connector.

This module must stay light to import: ``onyx.connectors.registry`` imports
every connector config eagerly to build ``CONNECTOR_CLASS_MAP``.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.atlassian_query import has_order_by
from onyx.connectors.connector_config import (
    BaseUrlCredentialBinding,
    ConnectorConfig,
    field_format_error,
)
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeOpaque,
)

# Atlassian Cloud project keys start with an uppercase letter and contain only
# uppercase ASCII letters and digits. Rejecting anything else here prevents a
# quote from breaking out of the ``project = "<key>"`` JQL clause.
_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*\Z")
_PROJECT_KEY_ERROR = (
    "Project key must start with an uppercase letter and contain only "
    "uppercase letters and digits."
)

JQL_ORDER_BY_ERROR = (
    "Unsupported clause: ORDER BY. Jira does not allow it inside the sync filter."
)
JQL_PARENTHESES_ERROR = "Invalid request_jql: unbalanced parentheses detected."


def has_balanced_parentheses(query: str) -> bool:
    """True if query has balanced parentheses outside of quoted strings."""
    count = 0
    in_quote: str | None = None
    escaped = False
    for ch in query:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == "(":
            count += 1
        elif ch == ")":
            count -= 1
            if count < 0:
                return False
    return count == 0 and in_quote is None


def validate_project_key(value: str) -> str:
    """Raise a field-format error unless ``value`` is a Jira Cloud key."""
    if not _PROJECT_KEY_RE.match(value or ""):
        raise field_format_error(_PROJECT_KEY_ERROR)
    return value


class JiraServiceManagementConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    """Typed shape of the connector's ``connector_specific_config``.

    Field names mirror the connector ``__init__`` kwargs one-for-one.
    Inheriting ``BaseUrlCredentialBinding`` binds ``base_url`` to the credential
    so the factory's credential-use rule can compare which site a credential is
    sent to.
    """

    project_key: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())]
    # Narrows the indexed ticket set further; complements project_key.
    request_jql: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

    @field_validator("project_key")
    @classmethod
    def _check_project_key(cls, value: str) -> str:
        """Validate that project_key adheres to Jira Cloud key naming rules."""
        return validate_project_key(value)

    @field_validator("request_jql")
    @classmethod
    def _check_request_jql(cls, value: str | None) -> str | None:
        """Validate that request_jql has no ORDER BY clause and has balanced parentheses."""
        if value is None:
            return None
        if has_order_by(value):
            raise field_format_error(JQL_ORDER_BY_ERROR)
        if not has_balanced_parentheses(value):
            raise field_format_error(JQL_PARENTHESES_ERROR)
        return value
