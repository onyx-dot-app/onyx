"""Jira Service Management (JSM) connector.

A JSM project is backed by a Jira project, and its service desk requests are
Jira issues reachable through the same Atlassian REST API the Jira connector
uses. The JSM connector therefore reuses the Jira crawl verbatim and only
re-binds it to ``DocumentSource.JSM`` so that:

* documents are attributed to Jira Service Management in search and the UI, and
* the connector is registered, configured and permission-synced as its own
  source.

The heavy lifting (JQL search, checkpointing, slim documents, permission sync,
reindex) is inherited from :class:`JiraConnector`; this module only overrides
the document source and the typed config.
"""

from typing import ClassVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jsm.config import JsmConnectorConfig

__all__ = ["JsmConnector"]


class JsmConnector(JiraConnector):
    """Indexes every ticket in a Jira Service Management project.

    Identical crawl to :class:`JiraConnector` (same REST API, same JQL scope,
    same checkpointing and permission sync), but stamps each document with
    ``DocumentSource.JSM`` and validates its config against
    :class:`JsmConnectorConfig`.
    """

    # Every document this connector emits is attributed to JSM.
    _document_source: ClassVar[DocumentSource] = DocumentSource.JSM

    @property
    def config(self) -> JsmConnectorConfig:
        return JsmConnectorConfig.model_validate(self.connector_specific_config)