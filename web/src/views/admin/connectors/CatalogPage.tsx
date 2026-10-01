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
import { InputTypeIn, Text } from "@opal/components";
import { useGridNavigation, useHotkey } from "@opal/hooks";
import { useFederatedConnectors } from "@/lib/hooks";
import { FederatedConnectorDetail } from "@/lib/types";
import { federatedSourceToRegularSource } from "@/lib/connectors/types/source";
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

/**
 * One source in the catalog. A source with a federated connector already
 * set up links to that connector instead of a fresh setup.
 */
function SourceTile({
  sourceMetadata,
  federatedConnectors,
}: {
  sourceMetadata: SourceMetadata;
  federatedConnectors?: FederatedConnectorDetail[];
}) {
  const t = useTranslations("admin.addConnector");
  const description = t(SOURCE_DESCRIPTION_KEYS[sourceMetadata.internalName]);

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

  const navigationUrl = existingFederatedConnector
    ? (`/admin/federated/${existingFederatedConnector.id}` as Route)
    : (sourceMetadata.adminUrl as Route);

  return (
    <ConnectorSourceCard
      sourceMetadata={sourceMetadata}
      description={description}
      navigationUrl={navigationUrl}
    />
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

  /**
   * Moves focus to the search field, with the caret at the end. A term
   * passed in replaces the current one.
   */
  function focusSearch(nextTerm?: string) {
    const input = searchInputRef.current;
    if (!input) return;
    if (nextTerm !== undefined) setSearchTerm(nextTerm);
    input.focus();
    // After React writes the new value.
    requestAnimationFrame(() => {
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });
  }

  useHotkey("/", () => focusSearch());

  // Arrows move between cards; leaving the top row, Escape, or typing
  // returns to search. "/" is left to the hotkey above.
  const { ref: catalogRef, focusFirst } = useGridNavigation({
    itemSelector: "[data-source-card]",
    onExit: (direction) => {
      if (direction === "up") focusSearch();
    },
    onEscape: () => focusSearch(),
    onTypeAhead: (character) => {
      if (character === "/") return false;
      focusSearch(rawSearchTerm + character);
    },
  });

  // Enter or ArrowDown moves to the first card. Escape clears the term,
  // then, on an empty field, leaves it.
  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // Keys that build or cancel an IME composition belong to the IME.
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (rawSearchTerm !== "") setSearchTerm("");
      else e.currentTarget.blur();
      return;
    }
    if ((e.key === "Enter" || e.key === "ArrowDown") && focusFirst()) {
      e.preventDefault();
    }
  }

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
                      <SourceTile
                        key={source.internalName}
                        sourceMetadata={source}
                        federatedConnectors={federatedConnectors}
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
                        <SourceTile
                          key={source.internalName}
                          sourceMetadata={source}
                          federatedConnectors={federatedConnectors}
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
