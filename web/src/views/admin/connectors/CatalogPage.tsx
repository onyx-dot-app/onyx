"use client";

import type { Route } from "next";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { Content, SettingsLayouts } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { SourceCategory, SourceMetadata } from "@/lib/search/types";
import { listSourceMetadata } from "@/lib/sources";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Tooltip, InputTypeIn, Text } from "@opal/components";
import { richNodes } from "@opal/utils";
import { useFederatedConnectors } from "@/lib/hooks";
import {
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/lib/connectors/utils";
import type { Credential } from "@/lib/connectors/types";
import { useSettings } from "@/lib/settings/hooks";
import { ConnectorSourceCard } from "@/lib/connectors/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  CATALOG_CATEGORIES,
  SOURCE_CATEGORY_LABEL_KEYS,
  SOURCE_DESCRIPTION_KEYS,
} from "@/lib/connectors/constants";

const route = ADMIN_ROUTES.CONNECTORS;

// Four columns at the full settings width, three and then two as the
// `sourcecards` container narrows.
const SOURCE_CARD_GRID =
  "grid grid-cols-2 @xl/sourcecards:grid-cols-3 @3xl/sourcecards:grid-cols-4 gap-2";

function SourceTileTooltipWrapper({
  sourceMetadata,
  federatedConnectors,
  slackCredentials,
}: {
  sourceMetadata: SourceMetadata;
  federatedConnectors?: FederatedConnectorDetail[];
  slackCredentials?: Credential<any>[];
}) {
  const t = useTranslations("admin.addConnector");
  const description = t(SOURCE_DESCRIPTION_KEYS[sourceMetadata.internalName]);

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
      return `/admin/federated/${existingFederatedConnector.id}` as Route;
    }

    // For all other sources (including Slack), use the regular admin URL
    return sourceMetadata.adminUrl as Route;
  }, [existingFederatedConnector, sourceMetadata]);

  // Compute whether to hide the tooltip
  const shouldHideTooltip =
    !existingFederatedConnector &&
    !hasExistingSlackCredentials &&
    !sourceMetadata.federated;

  // If tooltip should be hidden, just render the tile as a component
  if (shouldHideTooltip) {
    return (
      <ConnectorSourceCard
        sourceMetadata={sourceMetadata}
        description={description}
        navigationUrl={navigationUrl}
      />
    );
  }

  return (
    <Tooltip
      side="top"
      tooltip={
        existingFederatedConnector ? (
          <Text as="p" font="secondary-body" color="inherit">
            {richNodes(
              t.rich("sourceTile.tooltip.federatedConfigured", {
                strong: (chunks) => <strong>{chunks}</strong>,
              })
            )}
          </Text>
        ) : hasExistingSlackCredentials ? (
          <Text as="p" font="secondary-body" color="inherit">
            {richNodes(
              t.rich("sourceTile.tooltip.slackCredentialsFound", {
                strong: (chunks) => <strong>{chunks}</strong>,
              })
            )}
          </Text>
        ) : undefined
      }
    >
      <ConnectorSourceCard
        sourceMetadata={sourceMetadata}
        description={description}
        navigationUrl={navigationUrl}
      />
    </Tooltip>
  );
}

export default function ConnectorsPage() {
  const t = useTranslations("admin.addConnector");
  const adminRouteTitle = useAdminRouteTitle();
  const sources = useMemo(() => listSourceMetadata(), []);

  const [rawSearchTerm, setSearchTerm] = useState("");
  const searchTerm = useDeferredValue(rawSearchTerm);

  const { data: federatedConnectors } = useFederatedConnectors();
  const settings = useSettings();
  const { appName } = settings;

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
    const categories = CATALOG_CATEGORIES.reduce(
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
    // The extra-connectors setting hides the AI & Observability section.
    if (settings?.show_extra_connectors === false) {
      const filteredCategories = Object.entries(categories).filter(
        ([category]) => category !== SourceCategory.AiObservability
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

  // Enter or ArrowDown in the search field moves focus to the first card;
  // a focused card opens on Enter.
  const catalogRef = useRef<HTMLDivElement>(null);
  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter" && e.key !== "ArrowDown") return;
    const card =
      catalogRef.current?.querySelector<HTMLElement>("[data-source-card]");
    if (!card) return;
    e.preventDefault();
    card.focus();
  };

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header icon={route.icon} title={adminRouteTitle(route)}>
        <InputTypeIn
          type="text"
          searchIcon
          placeholder={t("search.placeholder")}
          ref={searchInputRef}
          value={rawSearchTerm} // keep the input bound to immediate state
          onChange={(event) => setSearchTerm(event.target.value)}
          onKeyDown={handleSearchKeyDown}
        />
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <div
          ref={catalogRef}
          className="@container/sourcecards flex flex-col gap-8"
        >
          <GeneralLayouts.Section
            gap={3}
            height="fit"
            alignItems="stretch"
            justifyContent="start"
          >
            <Content
              title={t("popular.title")}
              description={t("popular.description", { appName })}
              sizePreset="main-content"
              variant="section"
            />
            <GeneralLayouts.Section
              gap={8}
              height="fit"
              alignItems="stretch"
              justifyContent="start"
            >
              {dedupedPopular.length > 0 && (
                <GeneralLayouts.Section
                  gap={3}
                  height="fit"
                  alignItems="stretch"
                  justifyContent="start"
                >
                  <div className={SOURCE_CARD_GRID}>
                    {dedupedPopular.map((source) => (
                      <SourceTileTooltipWrapper
                        key={source.internalName}
                        sourceMetadata={source}
                        federatedConnectors={federatedConnectors}
                        slackCredentials={slackCredentials}
                      />
                    ))}
                  </div>
                </GeneralLayouts.Section>
              )}

              {Object.entries(categorizedSources)
                .filter(([_, sources]) => sources.length > 0)
                .map(([category, sources]) => (
                  <GeneralLayouts.Section
                    key={category}
                    gap={3}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Text font="main-ui-action" color="text-03">
                      {t(
                        SOURCE_CATEGORY_LABEL_KEYS[category as SourceCategory]
                      )}
                    </Text>
                    <div className={SOURCE_CARD_GRID}>
                      {sources.map((source) => (
                        <SourceTileTooltipWrapper
                          key={source.internalName}
                          sourceMetadata={source}
                          federatedConnectors={federatedConnectors}
                          slackCredentials={slackCredentials}
                        />
                      ))}
                    </div>
                  </GeneralLayouts.Section>
                ))}
            </GeneralLayouts.Section>
          </GeneralLayouts.Section>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
