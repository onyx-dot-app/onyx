"use client";
import { AdminPageTitle } from "@/components/admin/Title";
import { ConnectorIcon } from "@/components/icons/icons";
import { SourceCategory, SourceMetadata } from "@/lib/search/interfaces";
import { listSourceMetadata } from "@/lib/sources";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useFederatedConnectors } from "@/lib/hooks";
import {
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { Credential } from "@/lib/connectors/credentials";
import SourceTile from "@/components/SourceTile";

function SourceTileTooltipWrapper({
  sourceMetadata,
  preSelect,
  federatedConnectors,
  slackCredentials,
}: {
  sourceMetadata: SourceMetadata;
  preSelect?: boolean;
  federatedConnectors?: FederatedConnectorDetail[];
  slackCredentials?: Credential<any>[];
}) {
  // Check if there's already a federated connector for this source
  const existingFederatedConnector = useMemo(() => {
    if (!sourceMetadata.federated || !federatedConnectors) {
      return null;
    }

    return federatedConnectors.find(
      (connector) =>
        federatedSourceToRegularSource(connector.source) ===
        sourceMetadata.internalName
    );
  }, [sourceMetadata, federatedConnectors]);

  // For Slack specifically, check if there are existing non-federated credentials
  const isSlackTile = sourceMetadata.internalName === ValidSources.Slack;
  const hasExistingSlackCredentials = useMemo(() => {
    return isSlackTile && slackCredentials && slackCredentials.length > 0;
  }, [isSlackTile, slackCredentials]);

  // Determine the URL to navigate to
  const navigationUrl = useMemo(() => {
    // Special logic for Slack: if there are existing credentials, use the old flow
    if (isSlackTile && hasExistingSlackCredentials) {
      return "/admin/connectors/slack";
    }

    // Otherwise, use the existing logic
    if (existingFederatedConnector) {
      return `/admin/federated/${existingFederatedConnector.id}`;
    }
    return sourceMetadata.adminUrl;
  }, [
    isSlackTile,
    hasExistingSlackCredentials,
    existingFederatedConnector,
    sourceMetadata.adminUrl,
  ]);

  // Compute whether to hide the tooltip based on the provided condition
  const shouldHideTooltip =
    !(existingFederatedConnector && !hasExistingSlackCredentials) &&
    !hasExistingSlackCredentials &&
    !sourceMetadata.federated;

  // If tooltip should be hidden, just render the tile as a component
  if (shouldHideTooltip) {
    return (
      <SourceTile
        sourceMetadata={sourceMetadata}
        preSelect={preSelect}
        navigationUrl={navigationUrl}
        hasExistingSlackCredentials={!!hasExistingSlackCredentials}
      />
    );
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div>
            <SourceTile
              sourceMetadata={sourceMetadata}
              preSelect={preSelect}
              navigationUrl={navigationUrl}
              hasExistingSlackCredentials={!!hasExistingSlackCredentials}
            />
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-sm">
          {existingFederatedConnector && !hasExistingSlackCredentials ? (
            <p className="text-xs">
              <strong>Federated connector already configured.</strong> Click to
              edit the existing connector.
            </p>
          ) : hasExistingSlackCredentials ? (
            <p className="text-xs">
              <strong>Existing Slack credentials found.</strong> Click to manage
              the traditional Slack connector.
            </p>
          ) : sourceMetadata.federated ? (
            <p className="text-xs">
              {sourceMetadata.federatedTooltip ? (
                sourceMetadata.federatedTooltip
              ) : (
                <>
                  <strong>Federated Search.</strong> This will result in greater
                  latency and lower search quality.
                </>
              )}
            </p>
          ) : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function Page() {
  const sources = useMemo(() => listSourceMetadata(), []);

  const [searchTerm, setSearchTerm] = useState("");
  const { data: federatedConnectors } = useFederatedConnectors();

  // Fetch Slack credentials to determine navigation behavior
  const { data: slackCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(ValidSources.Slack),
    errorHandlingFetcher
  );

  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, []);
  const filterSources = useCallback(
    (sources: SourceMetadata[]) => {
      if (!searchTerm) return sources;
      const lowerSearchTerm = searchTerm.toLowerCase();
      return sources.filter(
        (source) =>
          source.displayName.toLowerCase().includes(lowerSearchTerm) ||
          source.category.toLowerCase().includes(lowerSearchTerm)
      );
    },
    [searchTerm]
  );

  const categorizedSources = useMemo(() => {
    const filtered = filterSources(sources);
    return Object.values(SourceCategory).reduce(
      (acc, category) => {
        acc[category] = sources.filter(
          (source) =>
            source.category === category &&
            (filtered.includes(source) ||
              category.toLowerCase().includes(searchTerm.toLowerCase()))
        );
        return acc;
      },
      {} as Record<SourceCategory, SourceMetadata[]>
    );
  }, [sources, filterSources, searchTerm]);

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      const filteredCategories = Object.entries(categorizedSources).filter(
        ([_, sources]) => sources.length > 0
      );
      if (
        filteredCategories.length > 0 &&
        filteredCategories[0] !== undefined &&
        filteredCategories[0][1].length > 0
      ) {
        const firstSource = filteredCategories[0][1][0];
        if (firstSource) {
          // Check if this source has an existing federated connector
          const existingFederatedConnector =
            firstSource.federated && federatedConnectors
              ? federatedConnectors.find(
                  (connector) =>
                    connector.source === `federated_${firstSource.internalName}`
                )
              : null;

          const url = existingFederatedConnector
            ? `/admin/federated/${existingFederatedConnector.id}`
            : firstSource.adminUrl;

          window.open(url, "_self");
        }
      }
    }
  };

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ConnectorIcon size={32} />}
        title="Add Connector"
        farRightElement={
          <Link href="/admin/indexing/status">
            <Button variant="success-reverse">See Connectors</Button>
          </Link>
        }
      />

      <input
        type="text"
        ref={searchInputRef}
        placeholder="Search connectors..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        onKeyDown={handleKeyPress}
        className="ml-1 w-96 h-9  flex-none rounded-md border border-border bg-background-50 px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />

      {Object.entries(categorizedSources)
        .filter(([_, sources]) => sources.length > 0)
        .map(([category, sources], categoryInd) => (
          <div key={category} className="mb-8">
            <div className="flex mt-8">
              <Title>{category}</Title>
            </div>
            <p>{getCategoryDescription(category as SourceCategory)}</p>
            <div className="flex flex-wrap gap-4 p-4">
              {sources.map((source, sourceInd) => (
                <SourceTileTooltipWrapper
                  preSelect={
                    searchTerm.length > 0 && categoryInd == 0 && sourceInd == 0
                  }
                  key={source.internalName}
                  sourceMetadata={source}
                  federatedConnectors={federatedConnectors}
                  slackCredentials={slackCredentials}
                />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

function getCategoryDescription(category: SourceCategory): string {
  switch (category) {
    case SourceCategory.Messaging:
      return "Integrate with messaging and communication platforms.";
    case SourceCategory.ProjectManagement:
      return "Link to project management and task tracking tools.";
    case SourceCategory.CustomerSupport:
      return "Connect to customer support and helpdesk systems.";
    case SourceCategory.CustomerRelationshipManagement:
      return "Integrate with customer relationship management platforms.";
    case SourceCategory.CodeRepository:
      return "Integrate with code repositories and version control systems.";
    case SourceCategory.Storage:
      return "Connect to cloud storage and file hosting services.";
    case SourceCategory.Wiki:
      return "Link to wiki and knowledge base platforms.";
    case SourceCategory.Other:
      return "Connect to other miscellaneous knowledge sources.";
    default:
      return "Connect to various knowledge sources.";
  }
}
