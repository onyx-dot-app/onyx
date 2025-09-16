"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
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
  className?: string;
}

export const ConnectorTitle = ({
  connector,
  ccPairId,
  ccPairName,
  owner,
  isPublic = true,
  isLink = true,
  showMetadata = true,
  className = "",
}: ConnectorTitleProps) => {
  const { t } = useTranslation();
  const sourceMetadata = getSourceMetadata(connector.source);

  let additionalMetadata = new Map<string, string>();
  if (connector.source === "github") {
    const typedConnector = connector as Connector<GithubConfig>;
    additionalMetadata.set(
      "Repo",
      typedConnector.connector_specific_config.repositories
        ? `${typedConnector.connector_specific_config.repo_owner}/${
            typedConnector.connector_specific_config.repositories.includes(",")
              ? "multiple repos"
              : typedConnector.connector_specific_config.repositories
          }`
        : `${typedConnector.connector_specific_config.repo_owner}/*`
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
  }

  const mainSectionClassName = `text-blue-500 dark:text-blue-100 flex w-fit ${className}`;
  const mainDisplay = (
    <>
      {sourceMetadata.icon({ size: 16 })}
      <div className="ml-1 my-auto text-xs font-medium truncate">
        {ccPairName || sourceMetadata.displayName}
      </div>
    </>
  );

  return (
    <div className="my-auto max-w-full">
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
        <div className="text-[10px] mt-0.5 text-gray-600 dark:text-gray-400">
          {Array.from(additionalMetadata.entries()).map(([key, value]) => {
            return (
              <div key={key} className="truncate">
                <i>
                  {key}
                  {t(k._2)}
                </i>{" "}
                {value}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
