import {
  ConfluenceConfig,
  Connector,
  GithubConfig,
  GitlabConfig,
  GoogleDriveConfig,
  JiraConfig,
  SlackConfig,
  ZulipConfig,
} from "@/lib/connectors/connectors";
import { getSourceMetadata } from "@/lib/sources";

import Link from "next/link";

interface ConnectorTitleProps {
  connector: Connector<any>;
  ccPairId: number;
  ccPairName: string | null | undefined;
  isPublic?: boolean;
  owner?: string;
  isLink?: boolean;
  showMetadata?: boolean;
}

export const ConnectorTitle = ({
  connector,
  ccPairId,
  ccPairName,
  owner,
  isPublic = true,
  isLink = true,
  showMetadata = true,
}: ConnectorTitleProps) => {
  const sourceMetadata = getSourceMetadata(connector.source);

  let additionalMetadata = new Map<string, string>();
  if (connector.source === "github") {
    const typedConnector = connector as Connector<GithubConfig>;
    additionalMetadata.set(
      "Repo",
      `${typedConnector.connector_specific_config.repo_owner}/${typedConnector.connector_specific_config.repo_name}`
    );
  } else if (connector.source === "gitlab") {
    const typedConnector = connector as Connector<GitlabConfig>;
    additionalMetadata.set(
      "Repo",
      `${typedConnector.connector_specific_config.project_owner}/${typedConnector.connector_specific_config.project_name}`
    );
  } else if (connector.source === "confluence") {
    const typedConnector = connector as Connector<ConfluenceConfig>;
    const wikiUrl = typedConnector.connector_specific_config.is_cloud
      ? `${typedConnector.connector_specific_config.wiki_base}/wiki/spaces/${typedConnector.connector_specific_config.space}`
      : `${typedConnector.connector_specific_config.wiki_base}/spaces/${typedConnector.connector_specific_config.space}`;
    additionalMetadata.set("Wiki URL", wikiUrl);
    if (typedConnector.connector_specific_config.page_id) {
      additionalMetadata.set(
        "Page ID",
        typedConnector.connector_specific_config.page_id
      );
    }
  } else if (connector.source === "jira") {
    const typedConnector = connector as Connector<JiraConfig>;
    additionalMetadata.set(
      "Jira Project URL",
      typedConnector.connector_specific_config.jira_project_url
    );
  } else if (connector.source === "slack") {
    const typedConnector = connector as Connector<SlackConfig>;
    if (
      typedConnector.connector_specific_config?.channels &&
      typedConnector.connector_specific_config?.channels.length > 0
    ) {
      additionalMetadata.set(
        "Channels",
        typedConnector.connector_specific_config.channels.join(", ")
      );
    }
    if (typedConnector.connector_specific_config.channel_regex_enabled) {
      additionalMetadata.set("Channel Regex Enabled", "True");
    }
  } else if (connector.source === "zulip") {
    const typedConnector = connector as Connector<ZulipConfig>;
    additionalMetadata.set(
      "Realm",
      typedConnector.connector_specific_config.realm_name
    );
  }

  const mainSectionClassName = "text-blue-500 flex w-fit";
  const mainDisplay = (
    <>
      {sourceMetadata.icon({ size: 20 })}
      <div className="ml-1 my-auto">
        {ccPairName || sourceMetadata.displayName}
      </div>
    </>
  );
  return (
    <div className="my-auto">
      {isLink ? (
        <Link
          className={mainSectionClassName}
          href={`/admin/connector/${ccPairId}`}
        >
          {mainDisplay}
        </Link>
      ) : (
        <div className={mainSectionClassName}>{mainDisplay}</div>
      )}
      {showMetadata && additionalMetadata.size > 0 && (
        <div className="text-xs mt-1">
          {Array.from(additionalMetadata.entries()).map(([key, value]) => {
            return (
              <div key={key}>
                <i>{key}:</i> {value}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
