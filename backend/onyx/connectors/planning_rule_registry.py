"""The planning rule of each source that has one (see ``planning_rule``).

A source without an entry uses the default rules for every edit. Sources
that share a config class can share a rule.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.bitbucket.config import (
    BitbucketConnectorConfig,
    bitbucket_planning_rule,
)
from onyx.connectors.confluence.config import (
    ConfluenceConnectorConfig,
    confluence_planning_rule,
)
from onyx.connectors.drupal_wiki.config import (
    DrupalWikiConnectorConfig,
    drupal_wiki_planning_rule,
)
from onyx.connectors.google_drive.config import (
    GoogleDriveConnectorConfig,
    google_drive_planning_rule,
)
from onyx.connectors.outlook.config import (
    OutlookConnectorConfig,
    outlook_planning_rule,
)
from onyx.connectors.planning_rule import PlanningRule, planning_rule
from onyx.connectors.salesforce.config import (
    SalesforceConnectorConfig,
    salesforce_planning_rule,
)
from onyx.connectors.slack.config import SlackConnectorConfig, slack_planning_rule
from onyx.connectors.teams.config import TeamsConnectorConfig, teams_planning_rule
from onyx.connectors.zoom.config import ZoomConnectorConfig, zoom_planning_rule

PLANNING_RULES: dict[DocumentSource, PlanningRule] = {
    DocumentSource.BITBUCKET: planning_rule(
        BitbucketConnectorConfig, bitbucket_planning_rule
    ),
    DocumentSource.CONFLUENCE: planning_rule(
        ConfluenceConnectorConfig, confluence_planning_rule
    ),
    DocumentSource.DRUPAL_WIKI: planning_rule(
        DrupalWikiConnectorConfig, drupal_wiki_planning_rule
    ),
    DocumentSource.GOOGLE_DRIVE: planning_rule(
        GoogleDriveConnectorConfig, google_drive_planning_rule
    ),
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
