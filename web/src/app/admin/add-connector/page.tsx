"use client";
import { AdminPageTitle } from "@/components/admin/Title";
import { ConnectorIcon } from "@/components/icons/icons";
import { SourceCategory, SourceMetadata } from "@/lib/search/interfaces";
import { listSourceMetadata } from "@/lib/sources";
import Title from "@/components/ui/title";
import Button from "@/refresh-components/buttons/Button";
import Link from "next/link";
import {
  useCallback,
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
import { SettingsContext } from "@/components/settings/SettingsProvider";
import SourceTile from "@/components/SourceTile";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";

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
            <Text inverted secondaryBody>
              <strong>Federated connector already configured.</strong> Click to
              edit the existing connector.
            </Text>
          ) : hasExistingSlackCredentials ? (
            <Text inverted secondaryBody>
              <strong>Existing Slack credentials found.</strong> Click to manage
              the traditional Slack connector.
            </Text>
          ) : sourceMetadata.federated ? (
            <Text inverted secondaryBody>
              {sourceMetadata.federatedTooltip ? (
                sourceMetadata.federatedTooltip
              ) : (
                <>
                  <strong>Federated Search.</strong> This will result in greater
                  latency and lower search quality.
                </>
              )}
            </Text>
          ) : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function Page() {
  const sources = useMemo(() => listSourceMetadata(), []);

  const [rawSearchTerm, setSearchTerm] = useState("");
  const searchTerm = useDeferredValue(rawSearchTerm);

  const { data: federatedConnectors } = useFederatedConnectors();
  const settings = useContext(SettingsContext);

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

  const popularSources = useMemo(() => {
    const filtered = filterSources(sources);
    return sources.filter(
      (source) =>
        source.isPopular &&
        (filtered.includes(source) ||
          source.displayName.toLowerCase().includes(searchTerm.toLowerCase()))
    );
  }, [sources, filterSources, searchTerm]);

  const categorizedSources = useMemo(() => {
    const filtered = filterSources(sources);
    const categories = Object.values(SourceCategory).reduce(
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
    // Filter out the "Other" category if show_extra_connectors is false
    if (settings?.settings?.show_extra_connectors === false) {
      const filteredCategories = Object.entries(categories).filter(
        ([category]) => category !== SourceCategory.Other
      );
      return Object.fromEntries(filteredCategories) as Record<
        SourceCategory,
        SourceMetadata[]
      >;
    }
    return categories;
  }, [
    sources,
    filterSources,
    searchTerm,
    settings?.settings?.show_extra_connectors,
  ]);

  // When searching, dedupe Popular against whatever is already in results
  const resultIds = useMemo(() => {
    if (!searchTerm) return new Set<string>();
    return new Set(
      Object.values(categorizedSources)
        .flat()
        .map((s) => s.internalName)
    );
  }, [categorizedSources, searchTerm]);

  const dedupedPopular = useMemo(() => {
    if (!searchTerm) return popularSources;
    return popularSources.filter((s) => !resultIds.has(s.internalName));
  }, [popularSources, resultIds, searchTerm]);

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
          <Button href="/admin/indexing/status" primary>
            See Connectors
          </Button>
        }
      />

      <InputTypeIn
        type="text"
        placeholder="Search Connectors"
        ref={searchInputRef}
        value={rawSearchTerm} // keep the input bound to immediate state
        onChange={(event) => setSearchTerm(event.target.value)}
        onKeyDown={handleKeyPress}
        className="w-96"
      />

      {dedupedPopular.length > 0 && (
        <div className="pt-8">
          <Text headingH3>Popular</Text>
          <div className="flex flex-wrap gap-4 p-4">
            {dedupedPopular.map((source) => (
              <SourceTileTooltipWrapper
                preSelect={false}
                key={source.internalName}
                sourceMetadata={source}
                federatedConnectors={federatedConnectors}
                slackCredentials={slackCredentials}
              />
            ))}
          </div>
        </div>
      )}

      {Object.entries(categorizedSources)
        .filter(([_, sources]) => sources.length > 0)
        .map(([category, sources], categoryInd) => (
          <div key={category} className="pt-8">
            <Text headingH3>{category}</Text>
            <div className="flex flex-wrap gap-4 p-4">
              {sources.map((source, sourceInd) => (
                <SourceTileTooltipWrapper
                  preSelect={
                    (searchTerm?.length ?? 0) > 0 &&
                    categoryInd == 0 &&
                    sourceInd == 0
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
