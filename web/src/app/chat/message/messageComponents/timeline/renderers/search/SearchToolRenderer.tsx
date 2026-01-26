import React from "react";
import { SvgSearch, SvgGlobe, SvgSearchMenu } from "@opal/icons";
import { SearchToolPacket } from "@/app/chat/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
  RendererResult,
} from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "./SearchChipList";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
  getMetadataTags,
} from "./searchStateUtils";
import Text from "@/refresh-components/texts/Text";

const queryToSourceInfo = (query: string, index: number): SourceInfo => ({
  id: `query-${index}`,
  title: query,
  sourceType: ValidSources.Web,
  icon: SvgSearch,
});

const resultToSourceInfo = (doc: OnyxDocument): SourceInfo => ({
  id: doc.document_id,
  title: doc.semantic_identifier || "",
  sourceType: doc.source_type,
  sourceUrl: doc.link,
  description: doc.blurb,
  metadata: {
    date: doc.updated_at || undefined,
    tags: getMetadataTags(doc.metadata),
  },
});

/**
 * SearchToolRenderer - Renders search tool execution steps
 *
 * RenderType modes:
 * - FULL: Shows all details (queries list + results). Header passed as `status` prop.
 *         Used when step is expanded in timeline.
 * - COMPACT: Shows only results (no queries). Header passed as `status` prop.
 *            Used when step is collapsed in timeline, still wrapped in StepContainer.
 * - HIGHLIGHT: Shows only results with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 */
export const SearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, results, isSearching, isComplete, isInternetSearch } =
    searchState;

  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  const hasResults = results.length > 0;

  const icon = isInternetSearch ? SvgGlobe : SvgSearchMenu;
  const queriesHeader = isInternetSearch
    ? "Searching the web for:"
    : "Searching internal documents for:";

  if (queries.length === 0) {
    return children([
      {
        icon,
        status: null,
        content: <div />,
        supportsCompact: true,
      },
    ]);
  }

  // HIGHLIGHT mode: header embedded in content, no StepContainer
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCompact: true,
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              {queriesHeader}
            </Text>
            <SearchChipList
              items={results}
              initialCount={INITIAL_RESULTS_TO_SHOW}
              expansionCount={RESULTS_PER_EXPANSION}
              getKey={(doc: OnyxDocument, index: number) =>
                doc.document_id ?? `result-${index}`
              }
              toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
              onClick={(doc: OnyxDocument) => {
                if (doc.link) {
                  window.open(doc.link, "_blank");
                }
              }}
              emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
            />
          </div>
        ),
      },
    ]);
  }

  // INLINE mode: dynamic phase-based content for collapsed streaming view
  if (isInline) {
    // Querying phase: show queries
    if (!hasResults) {
      return children([
        {
          icon: null,
          status: queriesHeader,
          supportsCompact: true,
          content: (
            <SearchChipList
              items={queries}
              initialCount={INITIAL_QUERIES_TO_SHOW}
              expansionCount={QUERIES_PER_EXPANSION}
              getKey={(_, index) => index}
              toSourceInfo={queryToSourceInfo}
              emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
              showDetailsCard={false}
              isQuery={true}
            />
          ),
        },
      ]);
    }

    // Reading results phase: show results
    return children([
      {
        icon: null,
        status: "Reading results",
        supportsCompact: true,
        content: (
          <SearchChipList
            items={results}
            initialCount={INITIAL_RESULTS_TO_SHOW}
            expansionCount={RESULTS_PER_EXPANSION}
            getKey={(doc: OnyxDocument, index: number) =>
              doc.document_id ?? `result-${index}`
            }
            toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
            onClick={(doc: OnyxDocument) => {
              if (doc.link) {
                window.open(doc.link, "_blank");
              }
            }}
            emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
          />
        ),
      },
    ]);
  }

  // FULL mode for web search: return 2 separate timeline steps
  if (!isCompact && isInternetSearch) {
    const steps: RendererResult[] = [
      {
        icon: SvgGlobe,
        status: "Searching the web for:",
        content: (
          <SearchChipList
            items={queries}
            initialCount={INITIAL_QUERIES_TO_SHOW}
            expansionCount={QUERIES_PER_EXPANSION}
            getKey={(_, index) => index}
            toSourceInfo={queryToSourceInfo}
            emptyState={
              !stopPacketSeen && !hasResults ? <BlinkingDot /> : undefined
            }
            showDetailsCard={false}
            isQuery={true}
          />
        ),
        supportsCompact: true,
      },
    ];

    // Add results step when results arrive
    if (hasResults) {
      steps.push({
        icon: SvgSearchMenu,
        status: "Reading results:",
        content: (
          <SearchChipList
            items={results}
            initialCount={INITIAL_RESULTS_TO_SHOW}
            expansionCount={RESULTS_PER_EXPANSION}
            getKey={(doc: OnyxDocument, index: number) =>
              doc.document_id ?? `result-${index}`
            }
            toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
            onClick={(doc: OnyxDocument) => {
              if (doc.link) {
                window.open(doc.link, "_blank");
              }
            }}
            emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
          />
        ),
        supportsCompact: true,
      });
    }

    return children(steps);
  }

  // Internal search or COMPACT mode: single-result behavior
  return children([
    {
      icon,
      status: queriesHeader,
      supportsCompact: true,
      content: (
        <div className="flex flex-col">
          {!isCompact && (
            <SearchChipList
              items={queries}
              initialCount={INITIAL_QUERIES_TO_SHOW}
              expansionCount={QUERIES_PER_EXPANSION}
              getKey={(_, index) => index}
              toSourceInfo={queryToSourceInfo}
              emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
              showDetailsCard={false}
              isQuery={true}
            />
          )}

          {(results.length > 0 || queries.length > 0) && (
            <>
              {!isCompact && (
                <Text as="p" mainUiMuted text03>
                  Reading results:
                </Text>
              )}
              <SearchChipList
                items={results}
                initialCount={INITIAL_RESULTS_TO_SHOW}
                expansionCount={RESULTS_PER_EXPANSION}
                getKey={(doc: OnyxDocument, index: number) =>
                  doc.document_id ?? `result-${index}`
                }
                toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
                onClick={(doc: OnyxDocument) => {
                  if (doc.link) {
                    window.open(doc.link, "_blank");
                  }
                }}
                emptyState={!stopPacketSeen ? <BlinkingDot /> : undefined}
              />
            </>
          )}
        </div>
      ),
    },
  ]);
};
