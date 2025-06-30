"use client";
import { SourceIcon } from "@/components/SourceIcon";
import { AdminPageTitle } from "@/components/admin/Title";
import { AlertIcon, ConnectorIcon, InfoIcon } from "@/components/icons/icons";
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
import { FederatedConnectorInfo } from "@/lib/types";

function SourceTile({
  sourceMetadata,
  preSelect,
  federatedConnectors,
}: {
  sourceMetadata: SourceMetadata;
  preSelect?: boolean;
  federatedConnectors?: FederatedConnectorInfo[];
}) {
  // Check if there's already a federated connector for this source
  const existingFederatedConnector = useMemo(() => {
    if (!sourceMetadata.federated || !federatedConnectors) {
      return null;
    }

    return federatedConnectors.find(
      (connector) =>
        connector.source === `federated_${sourceMetadata.internalName}`
    );
  }, [sourceMetadata, federatedConnectors]);

  // Determine the URL to navigate to
  const navigationUrl = useMemo(() => {
    if (existingFederatedConnector) {
      return `/admin/federated/${existingFederatedConnector.id}`;
    }
    return sourceMetadata.adminUrl;
  }, [existingFederatedConnector, sourceMetadata.adminUrl]);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Link
            className={`flex
              flex-col
              items-center
              justify-center
              p-4
              rounded-lg
              w-40
              cursor-pointer
              shadow-md
              hover:bg-accent-background-hovered
              relative
              ${
                preSelect
                  ? "bg-accent-background-hovered subtle-pulse"
                  : "bg-accent-background"
              }
            `}
            href={navigationUrl}
          >
            {sourceMetadata.federated && (
              <div className="absolute -top-2 -left-2 z-10 bg-white rounded-full p-1 shadow-md border border-orange-200">
                <AlertIcon
                  size={18}
                  className="text-orange-500 font-bold stroke-2"
                />
              </div>
            )}
            <SourceIcon
              sourceType={sourceMetadata.internalName}
              iconSize={24}
            />
            <p className="font-medium text-sm mt-2">
              {sourceMetadata.displayName}
            </p>
          </Link>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-sm">
          {existingFederatedConnector ? (
            <p className="text-xs">
              <strong>Federated connector already configured.</strong> Click to
              edit the existing connector.
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
                <SourceTile
                  preSelect={
                    searchTerm.length > 0 && categoryInd == 0 && sourceInd == 0
                  }
                  key={source.internalName}
                  sourceMetadata={source}
                  federatedConnectors={federatedConnectors}
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
