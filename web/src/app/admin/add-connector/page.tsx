"use client";
import { SettingsLayouts } from "@opal/layouts";
import { SourceCategory, SourceMetadata } from "@/lib/search/interfaces";
import { listSourceMetadata } from "@/lib/sources";
import { Button } from "@opal/components";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "@opal/components";
import { markdown } from "@opal/utils";
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
import { useSettings } from "@/lib/settings/hooks";
import SourceTile from "@/components/SourceTile";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminPageTitle } from "@/lib/admin-i18n";
import { useSourceCategoryLabel } from "@/lib/connector-i18n";

const route = ADMIN_ROUTES.ADD_CONNECTOR;

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
  const { t } = useTranslation();
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
    // If there's an existing federated connector, route to edit it
    if (existingFederatedConnector) {
      return `/admin/federated/${existingFederatedConnector.id}`;
    }

    // For all other sources (including Slack), use the regular admin URL
    return sourceMetadata.adminUrl;
  }, [existingFederatedConnector, sourceMetadata]);

  // Compute whether to hide the tooltip
  const shouldHideTooltip =
    !existingFederatedConnector &&
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
    <Tooltip
      side="top"
      tooltip={
        existingFederatedConnector
          ? markdown(t("admin.connector_setup.federated_configured"))
          : hasExistingSlackCredentials
            ? markdown(t("admin.connector_setup.slack_credentials_found"))
            : undefined
      }
    >
      <div>
        <SourceTile
          sourceMetadata={sourceMetadata}
          preSelect={preSelect}
          navigationUrl={navigationUrl}
          hasExistingSlackCredentials={!!hasExistingSlackCredentials}
        />
      </div>
    </Tooltip>
  );
}

function ConnectorCategorySection({
  category,
  sources,
  searchTerm,
  categoryInd,
  federatedConnectors,
  slackCredentials,
}: {
  category: SourceCategory;
  sources: SourceMetadata[];
  searchTerm: string;
  categoryInd: number;
  federatedConnectors?: FederatedConnectorDetail[];
  slackCredentials?: Credential<any>[];
}) {
  const categoryLabel = useSourceCategoryLabel(category);

  return (
    <div className="pt-8">
      <Text as="p" headingH3>
        {categoryLabel}
      </Text>
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
  );
}

export default function Page() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(ADMIN_ROUTES.ADD_CONNECTOR);
  const sources = useMemo(() => listSourceMetadata(), []);

  const [rawSearchTerm, setSearchTerm] = useState("");
  const searchTerm = useDeferredValue(rawSearchTerm);

  const { data: federatedConnectors } = useFederatedConnectors();
  const settings = useSettings();

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
    if (settings?.show_extra_connectors === false) {
      const filteredCategories = Object.entries(categories).filter(
        ([category]) => category !== SourceCategory.Other
      );
      return Object.fromEntries(filteredCategories) as Record<
        SourceCategory,
        SourceMetadata[]
      >;
    }
    return categories;
  }, [sources, filterSources, searchTerm, settings?.show_extra_connectors]);

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
    <SettingsLayouts.Root width="full">
      <SettingsLayouts.Header
        icon={route.icon}
        title={title}
        rightChildren={
          <Button href="/admin/indexing/status">
            {t("admin.connector_setup.see_connectors")}
          </Button>
        }
        divider
      />
      <SettingsLayouts.Body>
        <InputTypeIn
          type="text"
          placeholder={t("admin.connector_setup.search_placeholder")}
          ref={searchInputRef}
          value={rawSearchTerm} // keep the input bound to immediate state
          onChange={(event) => setSearchTerm(event.target.value)}
          onKeyDown={handleKeyPress}
        />

        {dedupedPopular.length > 0 && (
          <div className="pt-8">
            <Text as="p" headingH3>
              {t("admin.connector_setup.popular")}
            </Text>
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
            <ConnectorCategorySection
              key={category}
              category={category as SourceCategory}
              sources={sources}
              searchTerm={searchTerm}
              categoryInd={categoryInd}
              federatedConnectors={federatedConnectors}
              slackCredentials={slackCredentials}
            />
          ))}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
