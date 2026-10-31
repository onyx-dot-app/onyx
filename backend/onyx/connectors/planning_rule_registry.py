"""Per-source planning knowledge for connector edits: the planning rule of
each source that has one (see ``planning_rule``), and the sources whose
credential swaps usually need the full path.

A source without an entry uses the default rules for every edit. Sources
that share a config class can share a rule.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.asana.config import AsanaConnectorConfig, asana_planning_rule
from onyx.connectors.bitbucket.config import (
    BitbucketConnectorConfig,
    bitbucket_planning_rule,
)
from onyx.connectors.clickup.config import (
    ClickupConnectorConfig,
    clickup_planning_rule,
)
from onyx.connectors.confluence.config import (
    ConfluenceConnectorConfig,
    confluence_planning_rule,
)
from onyx.connectors.drupal_wiki.config import (
    DrupalWikiConnectorConfig,
    drupal_wiki_planning_rule,
)
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_planning import (
    FilePlanningData,
    file_planning_rule,
    load_file_planning_data,
)
from onyx.connectors.google_drive.config import (
    GoogleDriveConnectorConfig,
    google_drive_planning_rule,
)
from onyx.connectors.jira.config import JiraConnectorConfig, jira_planning_rule
from onyx.connectors.notion.config import (
    NotionConnectorConfig,
    notion_planning_rule,
)
from onyx.connectors.outlook.config import (
    OutlookConnectorConfig,
    outlook_planning_rule,
)
from onyx.connectors.planning_rule import (
    PlanningRule,
    planning_rule,
    planning_rule_with_data,
)
from onyx.connectors.salesforce.config import (
    SalesforceConnectorConfig,
    salesforce_planning_rule,
)
from onyx.connectors.slack.config import SlackConnectorConfig, slack_planning_rule
from onyx.connectors.teams.config import TeamsConnectorConfig, teams_planning_rule
from onyx.connectors.zoom.config import ZoomConnectorConfig, zoom_planning_rule

PLANNING_RULES: dict[DocumentSource, PlanningRule] = {
    DocumentSource.ASANA: planning_rule(AsanaConnectorConfig, asana_planning_rule),
    DocumentSource.BITBUCKET: planning_rule(
        BitbucketConnectorConfig, bitbucket_planning_rule
    ),
    DocumentSource.CLICKUP: planning_rule(
        ClickupConnectorConfig, clickup_planning_rule
    ),
    DocumentSource.CONFLUENCE: planning_rule(
        ConfluenceConnectorConfig, confluence_planning_rule
    ),
    DocumentSource.DRUPAL_WIKI: planning_rule(
        DrupalWikiConnectorConfig, drupal_wiki_planning_rule
    ),
    DocumentSource.FILE: planning_rule_with_data(
        LocalFileConnectorConfig,
        FilePlanningData,
        load_file_planning_data,
        file_planning_rule,
    ),
    DocumentSource.GOOGLE_DRIVE: planning_rule(
        GoogleDriveConnectorConfig, google_drive_planning_rule
    ),
    DocumentSource.JIRA: planning_rule(JiraConnectorConfig, jira_planning_rule),
    DocumentSource.NOTION: planning_rule(NotionConnectorConfig, notion_planning_rule),
    DocumentSource.OUTLOOK: planning_rule(
        OutlookConnectorConfig, outlook_planning_rule
    ),
    DocumentSource.SALESFORCE: planning_rule(
        SalesforceConnectorConfig, salesforce_planning_rule
    ),
    DocumentSource.SLACK: planning_rule(SlackConnectorConfig, slack_planning_rule),
    DocumentSource.TEAMS: planning_rule(TeamsConnectorConfig, teams_planning_rule),
    DocumentSource.ZOOM: planning_rule(ZoomConnectorConfig, zoom_planning_rule),
}

# Sources where a new credential usually sees different content (e.g. a
# scoped token), so a credential swap usually needs a full re-index and prune.
CREDENTIAL_SWAP_FULL_PATH_SOURCES: frozenset[DocumentSource] = frozenset(
    {DocumentSource.CONFLUENCE, DocumentSource.JIRA}
)
