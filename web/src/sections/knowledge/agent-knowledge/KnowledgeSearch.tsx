"use client";

import React from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { getSourceMetadata } from "@/lib/sources";
import type {
  ConnectedSource,
  HierarchyNodeSearchSummary,
} from "@/lib/hierarchy/interfaces";
import type { SearchDocWithContent } from "@/lib/search/interfaces";
import type { ValidSources } from "@/lib/types";
import { Button, Checkbox, Divider, InputTypeIn } from "@opal/components";
import {
  SvgArrowLeft,
  SvgChevronRight,
  SvgFileText,
  SvgFiles,
  SvgFolder,
  SvgSearch,
  SvgXCircle,
} from "@opal/icons";

import type { KnowledgeSearchResults } from "@/sections/knowledge/agent-knowledge/interfaces";

interface KnowledgeSearchBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  onBack: () => void;
  onFocus: () => void;
  isSearchMode: boolean;
}

export function KnowledgeSearchBar({
  query,
  onQueryChange,
  onSubmit,
  onClear,
  onBack,
  onFocus,
  isSearchMode,
}: KnowledgeSearchBarProps) {
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") onSubmit();
    if (e.key === "Escape" && isSearchMode) onBack();
  }

  return (
    <GeneralLayouts.Section
      flexDirection="row"
      alignItems="center"
      gap={0.25}
      height="auto"
    >
      {isSearchMode ? (
        <Button
          icon={SvgArrowLeft}
          prominence="tertiary"
          onClick={onBack}
          aria-label="exit-search"
        />
      ) : null}
      <GeneralLayouts.Section height="auto">
        <InputTypeIn
          searchIcon={!isSearchMode}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={onFocus}
          placeholder="Search documents..."
          variant="internal"
        />
      </GeneralLayouts.Section>
      {isSearchMode && query ? (
        <Button
          icon={SvgXCircle}
          prominence="tertiary"
          size="sm"
          onClick={onClear}
          aria-label="clear-search"
        />
      ) : null}
      {isSearchMode ? (
        <Button
          icon={SvgSearch}
          prominence="tertiary"
          size="sm"
          onClick={onSubmit}
          aria-label="submit-search"
        />
      ) : null}
    </GeneralLayouts.Section>
  );
}

interface KnowledgeSearchSidebarProps {
  connectedSources: ConnectedSource[];
  activeSourceFilter: ValidSources | null;
  onSourceFilterClick: (source: ValidSources | null) => void;
  resultCountBySource: Map<ValidSources, number>;
  vectorDbEnabled: boolean;
}

export function KnowledgeSearchSidebar({
  connectedSources,
  activeSourceFilter,
  onSourceFilterClick,
  resultCountBySource,
  vectorDbEnabled,
}: KnowledgeSearchSidebarProps) {
  const totalCount = Array.from(resultCountBySource.values()).reduce(
    (a, b) => a + b,
    0
  );

  return (
    <TableLayouts.SidebarLayout aria-label="knowledge-search-sidebar">
      <LineItem
        icon={SvgFiles}
        selected={activeSourceFilter === null}
        onClick={() => onSourceFilterClick(null)}
        rightChildren={
          totalCount > 0 ? (
            <Text mainUiAction className="text-action-link-05">
              {totalCount}
            </Text>
          ) : undefined
        }
      >
        All
      </LineItem>

      {vectorDbEnabled &&
        connectedSources.map((cs) => {
          const sourceMetadata = getSourceMetadata(cs.source);
          const count = resultCountBySource.get(cs.source) ?? 0;
          return (
            <LineItem
              key={cs.source}
              icon={sourceMetadata.icon}
              strokeIcon={false}
              selected={activeSourceFilter === cs.source}
              onClick={() => onSourceFilterClick(cs.source)}
              rightChildren={
                count > 0 ? (
                  <Text mainUiAction className="text-action-link-05">
                    {count}
                  </Text>
                ) : undefined
              }
            >
              {sourceMetadata.displayName}
            </LineItem>
          );
        })}
    </TableLayouts.SidebarLayout>
  );
}

interface KnowledgeSearchResultsPanelProps {
  committedQuery: string;
  searchQuery: string;
  isSearching: boolean;
  searchError: boolean;
  results: KnowledgeSearchResults | null;
  activeSourceFilter: ValidSources | null;
  selectedDocumentIds: string[];
  selectedFolderIds: number[];
  onToggleDocument: (id: string) => void;
  onToggleFolder: (id: number) => void;
  onNavigateToNode: (node: HierarchyNodeSearchSummary) => void;
}

export function KnowledgeSearchResultsPanel({
  committedQuery,
  searchQuery,
  isSearching,
  searchError,
  results,
  activeSourceFilter,
  selectedDocumentIds,
  selectedFolderIds,
  onToggleDocument,
  onToggleFolder,
  onNavigateToNode,
}: KnowledgeSearchResultsPanelProps) {
  if (!committedQuery) {
    return (
      <GeneralLayouts.Section
        alignItems="center"
        justifyContent="center"
        gap={0.5}
        aria-label="search-empty-state"
      >
        <SvgSearch size={32} className="stroke-text-04" />
        <Text secondaryBody text03>
          Input a search term and hit enter.
        </Text>
      </GeneralLayouts.Section>
    );
  }

  if (isSearching) {
    return (
      <GeneralLayouts.Section
        alignItems="center"
        justifyContent="center"
        aria-label="search-loading"
      >
        <Text secondaryBody text03>
          Searching...
        </Text>
      </GeneralLayouts.Section>
    );
  }

  if (searchError && committedQuery === searchQuery) {
    return (
      <GeneralLayouts.Section
        alignItems="center"
        justifyContent="center"
        gap={0.5}
        aria-label="search-error"
      >
        <Text secondaryBody text03>
          Search failed, please try again.
        </Text>
      </GeneralLayouts.Section>
    );
  }

  const allResults: Array<
    | { kind: "node"; item: HierarchyNodeSearchSummary }
    | { kind: "doc"; item: SearchDocWithContent }
  > = [
    ...(results?.nodes ?? []).map((n) => ({ kind: "node" as const, item: n })),
    ...(results?.docs ?? []).map((d) => ({ kind: "doc" as const, item: d })),
  ];

  const isStale = committedQuery !== searchQuery;

  const listContent =
    allResults.length === 0 ? (
      <GeneralLayouts.Section
        alignItems="center"
        justifyContent="center"
        gap={0.5}
        aria-label="search-no-results"
      >
        <Text secondaryBody text03>
          No results found
          {activeSourceFilter
            ? ` in ${getSourceMetadata(activeSourceFilter).displayName}`
            : ""}
          .
        </Text>
      </GeneralLayouts.Section>
    ) : (
      <GeneralLayouts.Section gap={0} alignItems="stretch" height="auto">
        <TableLayouts.TableRow>
          <TableLayouts.CheckboxCell />
          <TableLayouts.TableCell flex>
            <Text secondaryBody text03>
              Name
            </Text>
          </TableLayouts.TableCell>
          <TableLayouts.TableCell width={8}>
            <Text secondaryBody text03>
              Sources
            </Text>
          </TableLayouts.TableCell>
        </TableLayouts.TableRow>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <div className="overflow-y-auto max-h-80">
          {allResults.map((entry) => {
            if (entry.kind === "node") {
              const node = entry.item;
              const isSelected = selectedFolderIds.includes(node.id);
              const sourceMeta = getSourceMetadata(node.source);

              return (
                <TableLayouts.TableRow
                  key={`node-${node.id}`}
                  selected={isSelected}
                  onClick={() => onToggleFolder(node.id)}
                  aria-label={`search-node-${node.id}`}
                >
                  <TableLayouts.CheckboxCell>
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => onToggleFolder(node.id)}
                    />
                  </TableLayouts.CheckboxCell>
                  <TableLayouts.TableCell flex>
                    <GeneralLayouts.Section
                      flexDirection="row"
                      justifyContent="start"
                      alignItems="center"
                      gap={0.25}
                      height="auto"
                    >
                      <SvgFolder size={16} />
                      <GeneralLayouts.Section
                        flexDirection="column"
                        justifyContent="start"
                        alignItems="start"
                        gap={0}
                        height="auto"
                        className="min-w-0 grow"
                      >
                        <Truncated>{node.title}</Truncated>
                        {node.link && (
                          <Truncated text03 secondaryBody>
                            {node.link
                              .replace(/^https?:\/\//i, "")
                              .replace(/^www\./i, "")
                              .replace(/\/+$/, "")}
                          </Truncated>
                        )}
                      </GeneralLayouts.Section>
                      <Button
                        icon={SvgChevronRight}
                        prominence="tertiary"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onNavigateToNode(node);
                        }}
                        aria-label={`navigate-to-node-${node.id}`}
                      />
                    </GeneralLayouts.Section>
                  </TableLayouts.TableCell>
                  <TableLayouts.TableCell width={8}>
                    <TableLayouts.SourceIconsRow>
                      <sourceMeta.icon size={16} />
                    </TableLayouts.SourceIconsRow>
                  </TableLayouts.TableCell>
                </TableLayouts.TableRow>
              );
            }

            const doc = entry.item;
            const isSelected = selectedDocumentIds.includes(doc.document_id);
            const sourceMeta = getSourceMetadata(doc.source_type);

            return (
              <TableLayouts.TableRow
                key={`doc-${doc.document_id}-${doc.chunk_ind}`}
                selected={isSelected}
                onClick={() => onToggleDocument(doc.document_id)}
                aria-label={`search-doc-${doc.document_id}`}
              >
                <TableLayouts.CheckboxCell>
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => onToggleDocument(doc.document_id)}
                  />
                </TableLayouts.CheckboxCell>
                <TableLayouts.TableCell flex>
                  <GeneralLayouts.Section
                    flexDirection="row"
                    justifyContent="start"
                    alignItems="center"
                    gap={0.25}
                    height="auto"
                  >
                    <SvgFileText size={16} />
                    <GeneralLayouts.Section
                      flexDirection="column"
                      justifyContent="start"
                      alignItems="start"
                      gap={0}
                      height="auto"
                      className="min-w-0 grow"
                    >
                      <Truncated>{doc.semantic_identifier}</Truncated>
                      {doc.blurb && (
                        <Truncated text03 secondaryBody>
                          {doc.blurb}
                        </Truncated>
                      )}
                    </GeneralLayouts.Section>
                  </GeneralLayouts.Section>
                </TableLayouts.TableCell>
                <TableLayouts.TableCell width={8}>
                  <TableLayouts.SourceIconsRow>
                    <sourceMeta.icon size={16} />
                  </TableLayouts.SourceIconsRow>
                </TableLayouts.TableCell>
              </TableLayouts.TableRow>
            );
          })}
        </div>
      </GeneralLayouts.Section>
    );

  if (isStale) {
    return (
      <GeneralLayouts.Section
        alignItems="stretch"
        justifyContent="start"
        className="relative"
      >
        <GeneralLayouts.Section
          alignItems="stretch"
          justifyContent="start"
          className="opacity-40 pointer-events-none"
        >
          {listContent}
        </GeneralLayouts.Section>
        <GeneralLayouts.Section
          alignItems="center"
          justifyContent="center"
          className="absolute inset-0 z-10"
        >
          <Text secondaryBody text03>
            Press Enter for new results.
          </Text>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    );
  }

  return listContent;
}
