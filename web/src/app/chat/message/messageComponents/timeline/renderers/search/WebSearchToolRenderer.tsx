import React from "react";
import { SvgSearch, SvgGlobe, SvgSearchMenu, SvgCircle } from "@opal/icons";
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
  title: typeof query === "string" ? query : "",
  sourceType: ValidSources.Web,
  icon: SvgSearch,
});

const resultToSourceInfo = (doc: OnyxDocument): SourceInfo => ({
  id: doc.document_id,
  title:
    typeof doc.semantic_identifier === "string" ? doc.semantic_identifier : "",
  sourceType: doc.source_type,
  sourceUrl: doc.link,
  description: doc.blurb,
  metadata: {
    date: doc.updated_at || undefined,
    tags: getMetadataTags(doc.metadata),
  },
});

/**
 * WebSearchToolRenderer - Renders web search tool execution steps
 *
 * RenderType modes:
 * - FULL: Shows 2 timeline steps (queries list, then results).
 *         Used when step is expanded in timeline.
 * - HIGHLIGHT: Shows only results with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 * - INLINE: Phase-based (queries -> results) for collapsed streaming view.
 */
export const WebSearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, results } = searchState;

  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  const hasResults = results.length > 0;

  const queriesHeader = "Searching the web for:";

  if (queries.length === 0) {
    return children([
      {
        icon: SvgGlobe,
        status: null,
        content: <div />,
        supportsCollapsible: false,
      },
    ]);
  }

  // HIGHLIGHT mode: header embedded in content, no StepContainer
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
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
          supportsCollapsible: false,
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
        supportsCollapsible: false,
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

  // FULL mode: return 2 separate timeline steps
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
      supportsCollapsible: false,
    },
  ];

  // Add results step when results arrive
  if (hasResults) {
    steps.push({
      icon: SvgCircle,
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
      supportsCollapsible: false,
    });
  }

  return children(steps);
};
